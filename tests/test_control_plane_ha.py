"""Control plane has redundancy: enough control plane nodes and a healthy datastore.

These tests may currently fail — they document the HA posture we want.
"""

from __future__ import annotations

import k8s_helpers as k
import pytest

CONTROL_PLANE_LABELS = (
    "node-role.kubernetes.io/control-plane",
    "node-role.kubernetes.io/master",
    "node.kubernetes.io/microk8s-controlplane",
)


def control_plane_nodes() -> list[dict]:
    out = []
    for n in k.get_nodes():
        labels = n["metadata"].get("labels", {})
        if any(l in labels for l in CONTROL_PLANE_LABELS):
            out.append(n)
    return out


@pytest.mark.xfail(reason="my cluster does not have 3 control plane nodes yet")
def test_at_least_three_control_plane_nodes_exist():
    cps = control_plane_nodes()
    names = [k.node_name(n) for n in cps]
    assert (
        len(names) >= 3
    ), f"want >=3 control plane nodes for HA, found {len(names)}: {names}"


def test_at_least_two_control_plane_nodes_ready():
    ready = [n for n in control_plane_nodes() if k.node_is_ready(n)]
    names = [k.node_name(n) for n in ready]
    assert (
        len(ready) >= 2
    ), f"want >=2 Ready control plane nodes to survive a single failure, found {len(ready)}: {names}"


def test_etcd_componentstatus_healthy():
    """Datastore reports Healthy via componentstatuses (deprecated but still works)."""
    proc = k.kubectl("get", "componentstatuses", "-o", "json", check=False)
    if proc.returncode != 0:
        pytest.skip(f"componentstatuses unavailable: {proc.stderr.strip()}")
    import json

    items = json.loads(proc.stdout).get("items", [])
    etcd = [c for c in items if c["metadata"]["name"].startswith("etcd")]
    assert etcd, "no etcd componentstatus entries returned"
    for c in etcd:
        ok = any(
            cond.get("type") == "Healthy" and cond.get("status") == "True"
            for cond in c.get("conditions", [])
        )
        assert ok, f"{c['metadata']['name']} not healthy: {c.get('conditions')}"


def test_controller_manager_and_scheduler_healthy():
    proc = k.kubectl("get", "componentstatuses", "-o", "json", check=False)
    if proc.returncode != 0:
        pytest.skip(f"componentstatuses unavailable: {proc.stderr.strip()}")
    import json

    items = json.loads(proc.stdout).get("items", [])
    by_name = {c["metadata"]["name"]: c for c in items}
    for required in ("controller-manager", "scheduler"):
        c = by_name.get(required)
        assert c, f"no componentstatus entry for {required}"
        ok = any(
            cond.get("type") == "Healthy" and cond.get("status") == "True"
            for cond in c.get("conditions", [])
        )
        assert ok, f"{required} not healthy: {c.get('conditions')}"
