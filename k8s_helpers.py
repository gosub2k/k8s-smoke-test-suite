"""Tiny shell-out helpers around kubectl/ssh for the smoke tests.

Everything here is intentionally small and dependency-free. Pod specs are
plain dicts; we pipe them to `kubectl apply -f -` as JSON.
"""
from __future__ import annotations

import contextlib
import json
import re
import subprocess
import time
import uuid


class KubectlError(RuntimeError):
    pass


def kubectl(*args: str, stdin: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["kubectl", *args], input=stdin, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise KubectlError(f"kubectl {' '.join(args)}: {proc.stderr.strip()}")
    return proc


def kubectl_json(*args: str) -> dict:
    return json.loads(kubectl(*args, "-o", "json").stdout)


# ---- node introspection ----

def get_nodes() -> list[dict]:
    return kubectl_json("get", "nodes")["items"]


def node_name(node: dict) -> str:
    return node["metadata"]["name"]


def node_is_ready(node: dict) -> bool:
    return any(
        c["type"] == "Ready" and c["status"] == "True"
        for c in node.get("status", {}).get("conditions", [])
    )


def node_internal_ip(node: dict) -> str | None:
    for a in node.get("status", {}).get("addresses", []):
        if a["type"] == "InternalIP":
            return a["address"]
    return None


def ready_nodes() -> list[dict]:
    return [n for n in get_nodes() if node_is_ready(n)]


# ---- pod plumbing ----

def unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def make_pod(
    name: str,
    image: str,
    *,
    node: str | None = None,
    command: list[str] | None = None,
    host_network: bool = False,
    gpus: int = 0,
    nvidia_runtime: bool = False,
    pvcs: dict[str, str] | None = None,
) -> dict:
    """Build a minimal Pod manifest dict.

    pvcs: {mount_path: claim_name} — each PVC is mounted at the given path.
    """
    container: dict = {"name": "main", "image": image}
    if command:
        container["command"] = command
    if gpus:
        container["resources"] = {
            "requests": {"nvidia.com/gpu": gpus},
            "limits": {"nvidia.com/gpu": gpus},
        }

    volumes, mounts = [], []
    for i, (path, claim) in enumerate((pvcs or {}).items()):
        vol = f"vol{i}"
        volumes.append({"name": vol, "persistentVolumeClaim": {"claimName": claim}})
        mounts.append({"name": vol, "mountPath": path})
    if mounts:
        container["volumeMounts"] = mounts

    spec: dict = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name},
        "spec": {"restartPolicy": "Never", "containers": [container]},
    }
    if node:
        spec["spec"]["nodeSelector"] = {"kubernetes.io/hostname": node}
    if volumes:
        spec["spec"]["volumes"] = volumes
    if host_network:
        spec["spec"]["hostNetwork"] = True
    if gpus or nvidia_runtime:
        spec["spec"]["runtimeClassName"] = "nvidia"
    return spec


def apply(manifest: dict | str) -> None:
    body = manifest if isinstance(manifest, str) else json.dumps(manifest)
    kubectl("apply", "-f", "-", stdin=body)


def delete(kind: str, name: str, namespace: str = "default") -> None:
    kubectl("delete", kind, name, "-n", namespace, "--ignore-not-found=true",
            "--wait=false", check=False)


def wait_pod_phase(
    pod_name: str,
    phases: tuple[str, ...] = ("Succeeded", "Failed"),
    namespace: str = "default",
    timeout: int = 120,
) -> str:
    """Poll pod.status.phase; return final phase (last seen on timeout)."""
    deadline = time.time() + timeout
    last = "?"
    while time.time() < deadline:
        proc = kubectl("get", "pod", pod_name, "-n", namespace,
                       "-o", "jsonpath={.status.phase}", check=False)
        last = proc.stdout.strip() or "?"
        if last in phases:
            return last
        time.sleep(2)
    return last


def pod_logs(pod_name: str, namespace: str = "default") -> str:
    return kubectl("logs", pod_name, "-n", namespace, check=False).stdout


def pod_events(pod_name: str, namespace: str = "default") -> str:
    return kubectl("get", "events", "-n", namespace,
                   "--field-selector", f"involvedObject.name={pod_name}",
                   check=False).stdout


@contextlib.contextmanager
def transient_pod(spec: dict, namespace: str = "default"):
    """Apply pod, yield its name, always delete on exit."""
    name = spec["metadata"]["name"]
    apply(spec)
    try:
        yield name
    finally:
        delete("pod", name, namespace=namespace)


def run_pod(spec: dict, timeout: int = 120, namespace: str = "default") -> dict:
    """Apply a pod, wait for terminal phase, collect logs+events, clean up.

    Returns {phase, logs, events}.
    """
    with transient_pod(spec, namespace=namespace) as name:
        phase = wait_pod_phase(name, namespace=namespace, timeout=timeout)
        return {
            "phase": phase,
            "logs": pod_logs(name, namespace=namespace),
            "events": pod_events(name, namespace=namespace),
        }


# ---- network-interface probing (hostNetwork pod) ----

_ETH_PATTERNS = [re.compile(p) for p in (r"^en[opsx]", r"^eth\d")]
_WIFI_PATTERNS = [re.compile(p) for p in (r"^wl",)]


def iface_kind(name: str) -> str:
    """Classify a Linux interface name as 'ethernet', 'wifi', or 'other'."""
    if any(p.match(name) for p in _ETH_PATTERNS):
        return "ethernet"
    if any(p.match(name) for p in _WIFI_PATTERNS):
        return "wifi"
    return "other"


def list_ipv4_interfaces(node: str) -> dict[str, list[str]]:
    """{iface_name: [ipv4, ...]} for the node, via a hostNetwork busybox probe pod."""
    spec = make_pod(
        unique_name("iface-probe"),
        image="busybox",
        node=node,
        host_network=True,
        command=["sh", "-c", "ip -o addr show | awk '$3==\"inet\"{print $2,$4}'"],
    )
    result = run_pod(spec, timeout=60)
    if result["phase"] != "Succeeded":
        raise RuntimeError(
            f"iface probe on {node} failed: phase={result['phase']}\n"
            f"logs:\n{result['logs']}\nevents:\n{result['events']}"
        )
    out: dict[str, list[str]] = {}
    for line in result["logs"].splitlines():
        line = line.strip()
        if not line:
            continue
        iface, cidr = line.split()
        out.setdefault(iface, []).append(cidr.split("/")[0])
    return out


# ---- ssh fallback ----

def ssh(host: str, command: str, timeout: int = 5) -> subprocess.CompletedProcess:
    """Non-interactive SSH. Caller decides how to react to non-zero exits."""
    return subprocess.run(
        [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={timeout}",
            "-o", "StrictHostKeyChecking=accept-new",
            host, command,
        ],
        capture_output=True, text=True,
    )
