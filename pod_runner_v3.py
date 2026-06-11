#!/usr/bin/env python3
import subprocess
import argparse
import sys
import time
import uuid
import tempfile
import os

CUDA_TEST_IMAGE="nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0"

def create_pod_yaml_file(pod_name, host, command, image, gpus=0, nvidia_runtime=False, emptydir=False, hostpath=None):
    """Create pod YAML and write to a temporary file"""
    resources_section = ""
    if gpus > 0:
        resources_section = f"""
    resources:
      requests:
        nvidia.com/gpu: {gpus}
      limits:
        nvidia.com/gpu: {gpus}"""
    
    # Handle empty command - omit command/args entirely
    command_section = ""
    if command and command.strip():
        command_section = f"""
    command: ["/bin/sh", "-c"]
    args: ["{command}"]"""
    
    # Add runtimeClassName for multi-GPU workloads
    runtime_class_section = ""
    if gpus > 0 or nvidia_runtime:
        runtime_class_section = "\n  runtimeClassName: nvidia"

    # Add volume configuration for local storage
    volumes_section = ""
    volume_mounts_section = ""
    if emptydir:
        volumes_section = """
  volumes:
  - name: local-storage
    emptyDir: {}"""
        volume_mounts_section = """
    volumeMounts:
    - name: local-storage
      mountPath: /data"""
    elif hostpath:
        volumes_section = f"""
  volumes:
  - name: local-storage
    hostPath:
      path: {hostpath}
      type: DirectoryOrCreate"""
        volume_mounts_section = """
    volumeMounts:
    - name: local-storage
      mountPath: /data"""
    
    pod_yaml = f"""
apiVersion: v1
kind: Pod
metadata:
  name: {pod_name}
spec:
  restartPolicy: Never{runtime_class_section}
  nodeSelector:
    kubernetes.io/hostname: {host}
  containers:
  - name: debug-container
    image: {image}{command_section}
    tty: true
    stdin: true{resources_section}{volume_mounts_section}{volumes_section}
"""
    
    # Create temporary file
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    temp_file.write(pod_yaml)
    temp_file.close()
    
    return temp_file.name

def run_command_with_stderr_output(cmd_list, description=None, silent=False):
    """Run a command and first output to stderr what command will be run"""
    cmd_str = ' '.join(cmd_list)
    if not silent:
        if description:
            sys.stderr.write(f"Running {description}: {cmd_str}\n")
        else:
            sys.stderr.write(f"Running command: {cmd_str}\n")
    
    return subprocess.run(cmd_list, capture_output=True, text=True)

# TODO: better way to plumb all args through to create pod yaml
def run_pod_command(host, command="", image="busybox", timeout=60, gpus=0, interactive=False, nvidia=False, emptydir=False, hostpath=None):
    """Run a command in a Kubernetes pod"""
    
    # Generate unique pod name
    pod_name = f"debug-pod-{str(uuid.uuid4())[:8]}"

    # Create pod YAML file
    yaml_file = create_pod_yaml_file(pod_name, host, command, image, gpus, nvidia, emptydir, hostpath)
    
    # Output temp file path for future reference
    sys.stderr.write(f'YAML file created at: {yaml_file}\n')
    
    # Show YAML contents to stderr
    with open(yaml_file, 'r') as f:
        yaml_contents = f.read()
    sys.stderr.write('pod_yaml:\n--------\n'+yaml_contents+'\n')
    
    try:
        # Create pod
        print(f"Creating pod: {pod_name}")
        proc = run_command_with_stderr_output(
            ["kubectl", "apply", "-f", yaml_file],
            "pod creation"
        )
        
        if proc.returncode != 0:
            print(f"Error creating pod: {proc.stderr}")
            return False
        
        # Wait for pod to be running
        print("Waiting for pod to start...")
        for _ in range(timeout):
            time.sleep(1)
            result = run_command_with_stderr_output(
                ["kubectl", "get", "pod", pod_name, "-o", "jsonpath={.status.phase}"],
                "pod status check", silent=True
            )
            result_msg = result.stdout.strip()
            if result_msg == "Running":
                print(f"Pod {pod_name} is running")
                if interactive:
                    # Start interactive session
                    print(f"Starting interactive session in pod {pod_name}")
                    if command and command.strip():
                        exec_cmd = ["kubectl", "exec", "-it", pod_name, "--", command]
                    else:
                        exec_cmd = ["kubectl", "exec", "-it", pod_name, "--", "/bin/sh"]
                    sys.stderr.write(f"Running interactive command: {' '.join(exec_cmd)}\n")
                    subprocess.run(exec_cmd)
                    return True
                # For non-interactive, wait for completion and get logs
                print("Waiting for command to complete...")
                break
            elif result_msg in ["Succeeded", "Failed"]:
                # Pod completed before we even saw it running - handle immediately
                print(f"Pod {pod_name} {result_msg}")
                logs_result = run_command_with_stderr_output(
                    ["kubectl", "logs", pod_name],
                    "pod logs",
                    silent=True
                )
                if logs_result.returncode == 0:
                    print("--- Pod Output ---")
                    sys.stdout.write(logs_result.stdout)
                    print("------------------")
                else:
                    print(f"Error getting logs: {logs_result.stderr}")

                if result_msg != "Succeeded":  
                    print("\nPod events:")
                    events_result = run_command_with_stderr_output(["kubectl", "get", "events", "--field-selector", f"involvedObject.name={pod_name}"], "events check")
                    if events_result.stdout.strip():
                        print(events_result.stdout)
                    return False
                return True
            else:
                print(f"Pod {pod_name} {result.stdout.strip()}")
        else:
            print("Timeout waiting for pod to start")
            print("\nPod events:")
            events_result = run_command_with_stderr_output(["kubectl", "get", "events", "--field-selector", f"involvedObject.name={pod_name}"], "events check")
            if events_result.stdout.strip():
                print(events_result.stdout)
            return False

        # If we broke out because pod was running (non-interactive), wait for completion
        if not interactive:
            for _ in range(timeout):
                time.sleep(1)
                result = run_command_with_stderr_output(
                    ["kubectl", "get", "pod", pod_name, "-o", "jsonpath={.status.phase}"],
                    "pod completion check", silent=True
                )
                result_msg = result.stdout.strip()
                if result_msg in ["Succeeded", "Failed"]:
                    print(f"Pod {pod_name} {result_msg}")
                    # Get logs from completed pod
                    logs_result = run_command_with_stderr_output(
                        ["kubectl", "logs", pod_name],
                        "pod logs",
                        silent=True
                    )
                    if logs_result.returncode == 0:
                        print("--- Pod Output ---")
                        print(logs_result.stdout)
                        print("------------------")
                    else:
                        print(f"Error getting logs: {logs_result.stderr}")

                    if result_msg != "Succeeded":  
                        print("\nPod events:")
                        events_result = run_command_with_stderr_output(["kubectl", "get", "events", "--field-selector", f"involvedObject.name={pod_name}"], "events check")
                        if events_result.stdout.strip():
                            print(events_result.stdout)
                        return False
                    return True
            else:
                # Timeout waiting for completion - still get logs if available
                print("Timeout waiting for pod to complete, getting available logs...")
                logs_result = run_command_with_stderr_output(
                    ["kubectl", "logs", pod_name],
                    "pod logs",
                    silent=True
                )
                if logs_result.returncode == 0 and logs_result.stdout.strip():
                    print("--- Pod Output (partial) ---")
                    print(logs_result.stdout)
                    print("----------------------------")
                return False

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    
    finally:
        # Clean up
        print(f"\nCleaning up pod: {pod_name}")
        run_command_with_stderr_output(
            ["kubectl", "delete", "pod", pod_name],
            "pod cleanup"
        )
    
    return True

def main():
    parser = argparse.ArgumentParser(
        description='Run commands in GPU-enabled Kubernetes pods',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:

        """
    )

    parser.add_argument('host', type=str, help="node name to run the container on")
    parser.add_argument('command', nargs='?', default="", help='Command to run in the pod (optional, empty string will use container default)')
    parser.add_argument('-i', '--image', default='busybox', 
                       help='Container image to use (default: busybox)')
    parser.add_argument('-g', '--gpus', type=int, default=0,
                       help='Number of GPUs to request (default: 0, no GPU resources)')
    parser.add_argument('-C', '--nvidia', action='store_true',
                       help='Request nvidia container runtime regardless of number of gpus')
    parser.add_argument('--interactive', action='store_true',
                       help='Start an interactive session in the pod')
    parser.add_argument('--emptydir', action='store_true',
                       help='Mount an emptyDir volume at /data (temporary storage)')
    parser.add_argument('--hostpath', type=str, default=None,
                       help='Mount a hostPath volume at /data from the specified host path')

    args = parser.parse_args()
    
    run_pod_command(args.host, command=args.command, image=args.image, gpus=args.gpus, interactive=args.interactive, nvidia=args.nvidia, emptydir=args.emptydir, hostpath=args.hostpath)

if __name__ == "__main__":
    main()
