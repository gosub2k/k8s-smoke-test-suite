"""NodePort cross-node reachability via an nginx Deployment + Service.

A NodePort service must answer on every node's IP, regardless of where the
backend pod is actually scheduled — kube-proxy iptables/IPVS rules forward
to the pod across nodes. We verify two paths:

  1) wget from the local shell to each Ready node's InternalIP:nodePort
  2) ssh to a Ready node and wget back to a peer's InternalIP:nodePort
"""
from __future__ import annotations

import shutil
import subprocess
import time

import pytest

import k8s_helpers as k

NAME = "smoke-nginx"
NODEPORT = 30888

_READY = k.ready_nodes()
_PAIRS = [(s, t) for s in _READY for t in _READY if k.node_name(s) != k.node_name(t)]


def _deployment() -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": NAME},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": NAME}},
            "template": {
                "metadata": {"labels": {"app": NAME}},
                "spec": {
                    "containers": [{
                        "name": "nginx",
                        "image": "nginx:alpine",
                        "ports": [{"containerPort": 80}],
                    }],
                },
            },
        },
    }


def _service() -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": NAME},
        "spec": {
            "type": "NodePort",
            "selector": {"app": NAME},
            "ports": [{"port": 80, "targetPort": 80, "nodePort": NODEPORT}],
        },
    }


@pytest.fixture(scope="module")
def nginx_nodeport():
    """Create nginx Deployment + NodePort Service; yield the port; teardown after."""
    k.apply(_deployment())
    k.apply(_service())
    try:
        deadline = time.time() + 180
        while time.time() < deadline:
            dep = k.kubectl_json("get", "deployment", NAME)
            available = (dep.get("status") or {}).get("availableReplicas", 0) or 0
            if available >= 1:
                yield NODEPORT
                return
            time.sleep(2)
        pytest.fail(
            f"deployment '{NAME}' never had availableReplicas>=1 in 180s; "
            "check pod scheduling / CNI on Ready nodes."
        )
    finally:
        k.delete("svc", NAME)
        k.delete("deployment", NAME)


def _looks_like_nginx(body: str) -> bool:
    lo = body.lower()
    return "nginx" in lo or "welcome" in lo


@pytest.mark.parametrize("node", _READY, ids=k.node_name)
def test_nodeport_reachable_from_local_shell(node, nginx_nodeport):
    if shutil.which("wget") is None:
        pytest.skip("wget not installed locally")
    ip = k.node_internal_ip(node)
    url = f"http://{ip}:{nginx_nodeport}/"
    proc = subprocess.run(
        ["wget", "-qO-", "--timeout=5", "--tries=1", url],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, (
        f"wget {url} from local shell rc={proc.returncode}: {proc.stderr.strip()}"
    )
    assert _looks_like_nginx(proc.stdout), f"unexpected body from {url}: {proc.stdout!r}"


@pytest.mark.parametrize(
    "src,dst",
    _PAIRS,
    ids=[f"{k.node_name(s)}_to_{k.node_name(t)}" for s, t in _PAIRS],
)
def test_nodeport_reachable_via_ssh_to_peer(src, dst, nginx_nodeport):
    src_name = k.node_name(src)
    dst_ip = k.node_internal_ip(dst)
    url = f"http://{dst_ip}:{nginx_nodeport}/"
    proc = k.ssh(src_name, f"wget -qO- --timeout=5 --tries=1 {url}")
    if proc.returncode != 0 and any(
        m in proc.stderr for m in ("Permission denied", "Host key", "Could not resolve hostname")
    ):
        pytest.skip(f"ssh {src_name} unavailable: {proc.stderr.strip()}")
    assert proc.returncode == 0, (
        f"ssh {src_name} 'wget {url}' rc={proc.returncode}: {proc.stderr.strip()}"
    )
    assert _looks_like_nginx(proc.stdout), (
        f"unexpected body via ssh {src_name} from {url}: {proc.stdout!r}"
    )
