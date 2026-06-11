"""1-GPU pod with nvidia runtime can run torch + CUDA. Expected to fail today."""

import config_helpers as conf
import k8s_helpers as k
import output_helpers as dbg
import pytest


def first_gpu_ready_node() -> str | None:
    for n in k.ready_nodes():
        alloc = n.get("status", {}).get("allocatable", {})
        if int(alloc.get("nvidia.com/gpu", "0") or 0) >= 1:
            return k.node_name(n)
    return None


@pytest.mark.skip("need to figure out torch and cuda version first")
def test_gpu_torch_runs():
    node = conf.Config().get("special_gpu_node")
    if node is None:
        node = first_gpu_ready_node()
        if not node:
            pytest.skip("no Ready node with an allocatable nvidia.com/gpu")
    if node not in list(map(k.node_name, k.get_nodes())):
        pytest.skip(f"node {node} not found in k8s api")
    dbg.debug(f"testing gpu node: {node}")
    script = (
        "import torch;"
        "assert torch.cuda.is_available(), 'cuda not available';"
        "x = torch.randn(64, 64, device='cuda');"
        "y = (x @ x).sum().item();"
        "print('cuda_ok', y)"
    )
    spec = k.make_pod(
        k.unique_name("torch-gpu"),
        image="pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime",
        node=node,
        command=["python", "-c", script],
        gpus=1,
        nvidia_runtime=True,
    )
    result = k.run_pod(spec, timeout=60)
    assert result["phase"] == "Succeeded", (
        f"GPU torch pod did not succeed: phase={result['phase']}\n"
        f"logs:\n{result['logs']}\nevents:\n{result['events']}"
    )
    assert "cuda_ok" in result["logs"]
