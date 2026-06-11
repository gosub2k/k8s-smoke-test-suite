"""kubernetes-dashboard is deployed, running, and reachable on its NodePort."""
from __future__ import annotations

import pytest

import k8s_helpers as k
import output_helpers as oh

DASHBOARD_NS = "kube-system"
DASHBOARD_NAME = "kubernetes-dashboard"


def test_dashboard_deployment_exists():
    # Raises KubectlError (failing the test) if the deployment is missing.
    k.kubectl("get", "deployment", DASHBOARD_NAME, "-n", DASHBOARD_NS)


def test_dashboard_pods_up():
    dep = k.kubectl_json("get", "deployment", DASHBOARD_NAME, "-n", DASHBOARD_NS)
    desired = dep["spec"].get("replicas", 1)
    available = dep.get("status", {}).get("availableReplicas", 0) or 0
    assert available >= 1, (
        f"{DASHBOARD_NAME}: only {available}/{desired} replicas Available"
    )


def test_dashboard_nodeport_open():
    svc = k.kubectl_json("get", "svc", DASHBOARD_NAME, "-n", DASHBOARD_NS)
    assert svc["spec"]["type"] == "NodePort", (
        f"{DASHBOARD_NAME} service is {svc['spec']['type']}, expected NodePort"
    )
    node_port = next(
        (p["nodePort"] for p in svc["spec"]["ports"] if p.get("nodePort")), None
    )
    assert node_port, f"{DASHBOARD_NAME} service has no nodePort: {svc['spec']['ports']}"

    ready = k.ready_nodes()
    if not ready:
        pytest.skip("no Ready nodes to probe from")
    target_ip = k.node_internal_ip(ready[0])
    oh.debug(f"probing {target_ip}:{node_port}")

    # hostNetwork bypasses CNI: we want to test that the NodePort works from
    # a node, not whether pod networking is healthy.
    probe = k.make_pod(
        k.unique_name("dash-probe"),
        image="busybox",
        node=k.node_name(ready[0]),
        host_network=True,
        command=["sh", "-c", f"nc -z -w 3 {target_ip} {node_port}"],
    )
    result = k.run_pod(probe, timeout=60)
    assert result["phase"] == "Succeeded", (
        f"NodePort {target_ip}:{node_port} not reachable: "
        f"phase={result['phase']}\nlogs:\n{result['logs']}\nevents:\n{result['events']}"
    )
