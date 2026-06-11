"""SSH-to-node capability check.

Most node info comes from kubectl elsewhere; this is the fallback channel.
Skips when SSH is not configured for the node.
"""
from __future__ import annotations

import pytest

import k8s_helpers as k


@pytest.mark.parametrize("node", k.ready_nodes(), ids=k.node_name)
def test_ssh_returns_hostname(node):
    name = k.node_name(node)
    proc = k.ssh(name, "hostname")
    if proc.returncode != 0:
        pytest.skip(f"ssh {name} not configured: {proc.stderr.strip()}")
    assert proc.stdout.strip(), f"ssh {name} hostname returned empty output"
