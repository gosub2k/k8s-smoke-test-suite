"""Flannel network plumbing.

Flannel is installed as a DaemonSet via `kubectl apply` (not Helm). Without an
explicit override, flanneld auto-detects an IP per node, which can land on the
wrong interface (wifi) on multi-homed hosts. The canonical per-node knob is the
`public-ip-overwrite` annotation; there is no per-node interface-name annotation
in stock flannel.
"""
from __future__ import annotations

import pytest

import k8s_helpers as k

PUBLIC_IP_OVERWRITE = "flannel.alpha.coreos.com/public-ip-overwrite"


@pytest.mark.parametrize("node", k.ready_nodes(), ids=k.node_name)
def test_flannel_public_ip_overwrite_on_multi_iface_nodes(node):
    """Multi-homed nodes pin flannel to the wired IP. Single-iface nodes skip."""
    name = k.node_name(node)
    ifaces = k.list_ipv4_interfaces(name)
    eth = [n for n in ifaces if k.iface_kind(n) == "ethernet"]
    wifi = [n for n in ifaces if k.iface_kind(n) == "wifi"]
    if not (eth and wifi):
        pytest.skip(f"{name}: only one kind of interface (eth={eth}, wifi={wifi})")

    eth_ips = [ip for n in eth for ip in ifaces[n]]
    overwrite = node["metadata"].get("annotations", {}).get(PUBLIC_IP_OVERWRITE)
    assert overwrite, (
        f"{name} has eth ({eth}) + wifi ({wifi}) but no {PUBLIC_IP_OVERWRITE} annotation. "
        f"Set it to one of {eth_ips} so flannel pins the tunnel to the wired interface."
    )
    assert overwrite in eth_ips, (
        f"{name} {PUBLIC_IP_OVERWRITE}={overwrite} is not one of the ethernet IPs {eth_ips}"
    )


@pytest.mark.parametrize("node", k.get_nodes(), ids=k.node_name)
def test_node_has_pod_cidr(node):
    """Every registered node must have podCIDR / podCIDRs assigned in .spec."""
    name = k.node_name(node)
    spec = node["spec"]
    assert spec.get("podCIDR"), f"{name}: .spec.podCIDR missing"
    assert spec.get("podCIDRs"), f"{name}: .spec.podCIDRs missing"
