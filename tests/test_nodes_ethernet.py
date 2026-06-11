"""Ready nodes with both ethernet and wifi must bind their InternalIP to the ethernet interface."""
from __future__ import annotations

import pytest

import k8s_helpers as k


@pytest.mark.parametrize("node", k.ready_nodes(), ids=k.node_name)
def test_node_uses_ethernet_when_both_available(node):
    name = k.node_name(node)
    internal_ip = k.node_internal_ip(node)
    assert internal_ip, f"no InternalIP for {name}"

    ifaces = k.list_ipv4_interfaces(name)
    eth = [n for n in ifaces if k.iface_kind(n) == "ethernet"]
    wifi = [n for n in ifaces if k.iface_kind(n) == "wifi"]

    if not (eth and wifi):
        pytest.skip(f"{name}: not both eth+wifi present (eth={eth}, wifi={wifi})")

    bound = next((n for n, ips in ifaces.items() if internal_ip in ips), None)
    assert bound in eth, (
        f"{name}: InternalIP {internal_ip} bound to {bound!r}, expected one of ethernet={eth} "
        f"(wifi available={wifi})"
    )
