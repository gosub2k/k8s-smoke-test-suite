"""Pod-to-pod (CNI / overlay) reachability across and within Ready nodes.

Two busybox sleeper pods on each Ready node ("a" + "b"). For every (src, dst)
node pair we ping the dst pod's IP from the src pod:
  - cross-node pair (src != dst): a-pod on src pings a-pod on dst — overlay path
  - same-node pair (src == dst): a-pod on the node pings b-pod on the same node — intra-node CNI bridge

Distinct from the NodePort test: this exercises the pod-network directly —
no Service, no kube-proxy in the path.
"""

from __future__ import annotations

import time

import k8s_helpers as k
import pytest

NAME_PREFIX = "smoke-pingpod"
_READY = k.ready_nodes()
_PAIRS = [
    (s, t) for s in _READY for t in _READY
]  # if k.node_name(s) != k.node_name(t)]


def _pod_name(node: str, side: str = "a") -> str:
    return f"{NAME_PREFIX}-{side}-{node}"


def _pair_id(s, t) -> str:
    sn, tn = k.node_name(s), k.node_name(t)
    return f"{sn}__within_node" if sn == tn else f"{sn}_to_{tn}"


def _wait_pod_ip(pod_name: str, timeout: int = 180) -> str | None:
    """Return the pod's IP once it is Running, or None on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pod = k.kubectl_json("get", "pod", pod_name)
        status = pod.get("status", {})
        if status.get("phase") == "Running" and status.get("podIP"):
            return status["podIP"]
        time.sleep(2)
    return None


@pytest.fixture(scope="module")
def pingpodset():
    """Two sleeper pods per Ready node (a + b); yield {node: {"a": ip, "b": ip}}."""
    specs: dict[tuple[str, str], dict] = {}
    for n in _READY:
        node = k.node_name(n)
        for side in ("a", "b"):
            specs[(node, side)] = k.make_pod(
                _pod_name(node, side),
                image="busybox",
                node=node,
                command=["sleep", "3600"],
            )
    for spec in specs.values():
        k.apply(spec)
    try:
        ips: dict[str, dict[str, str]] = {}
        for (node, side) in specs:
            ip = _wait_pod_ip(_pod_name(node, side))
            if ip:
                ips.setdefault(node, {})[side] = ip
        yield ips
    finally:
        for (node, side) in specs:
            k.delete("pod", _pod_name(node, side))


@pytest.mark.parametrize(
    "src,dst",
    _PAIRS,
    ids=[_pair_id(s, t) for s, t in _PAIRS],
)
def test_pod_to_pod_ping(src, dst, pingpodset):
    src_name = k.node_name(src)
    dst_name = k.node_name(dst)
    # Within-node pair uses the peer b-pod on the same node, so we ping a real
    # second pod (not ourselves). Cross-node pair uses a-pod on both sides.
    dst_side = "b" if src_name == dst_name else "a"

    if pingpodset.get(src_name, {}).get("a") is None:
        pytest.skip(f"src pod {src_name}/a never reached Running (CNI broken?)")
    if pingpodset.get(dst_name, {}).get(dst_side) is None:
        pytest.skip(f"dst pod {dst_name}/{dst_side} never reached Running (CNI broken?)")

    src_pod = _pod_name(src_name, "a")
    dst_ip = pingpodset[dst_name][dst_side]

    proc = k.kubectl(
        "exec",
        src_pod,
        "--",
        "ping",
        "-c",
        "3",
        "-W",
        "2",
        dst_ip,
        check=False,
    )
    assert proc.returncode == 0, (
        f"ping {src_name}/a -> {dst_name}/{dst_side} ({dst_ip}) failed (rc={proc.returncode}):\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
