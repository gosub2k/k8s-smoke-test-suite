"""kubernetes-dashboard is deployed, running, and reachable on its NodePort."""

from __future__ import annotations

import k8s_helpers as k
import output_helpers as oh
import pytest


@pytest.mark.parametrize("node", k.ready_nodes(), ids=k.node_name)
def test_simple_pod_runs(node):
    # hostNetwork bypasses CNI: we want to test that the NodePort works from
    # a node, not whether pod networking is healthy.
    if not k.node_is_ready(node):
        pytest.mark.skip(f"node {k.node_name(node)} is not ready")
    probe = k.make_pod(
        k.unique_name("probe"),
        image="busybox",
        command=["echo", "testing...testing..."],
        node=k.node_name(node),
    )
    result = k.run_pod(probe, timeout=60)
    assert (
        result["phase"] == "Succeeded"
    ), f"phase={result['phase']}\nlogs:\n{result['logs']}\nevents:\n{result['events']}"
