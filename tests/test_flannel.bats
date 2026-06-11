#!/usr/bin/env bats
# Flannel network plumbing: correct public-ip-overwrite annotation and podCIDR.
load helpers

PUBLIC_IP_OVERWRITE="flannel.alpha.coreos.com/public-ip-overwrite"

@test "multi-homed nodes have flannel public-ip-overwrite set to an ethernet IP" {
  local failed=()
  while read -r node; do
    local eth=() wifi=() eth_ips=()
    while IFS=" " read -r iface ip; do
      case $(iface_kind "$iface") in
        ethernet) eth+=("$iface"); eth_ips+=("$ip") ;;
        wifi)     wifi+=("$iface") ;;
      esac
    done < <(list_ipv4_interfaces "$node" 2>/dev/null || true)
    [[ ${#eth[@]} -gt 0 && ${#wifi[@]} -gt 0 ]] || continue

    overwrite=$(kubectl get node "$node" -o json | \
      jq -r --arg k "$PUBLIC_IP_OVERWRITE" '.metadata.annotations[$k] // empty')
    if [[ -z "$overwrite" ]]; then
      failed+=("$node: missing $PUBLIC_IP_OVERWRITE (eth=${eth[*]}, wifi=${wifi[*]})")
      continue
    fi
    local found=false
    for ip in "${eth_ips[@]}"; do [[ "$overwrite" == "$ip" ]] && found=true && break; done
    $found || failed+=("$node: $PUBLIC_IP_OVERWRITE=$overwrite not in ethernet IPs ${eth_ips[*]}")
  done < <(ready_nodes)
  [[ ${#failed[@]} -eq 0 ]] || fail "$(printf '%s\n' "${failed[@]}")"
}

@test "all nodes have podCIDR assigned" {
  local failed=()
  while read -r node; do
    cidr=$(kubectl get node "$node" -o jsonpath='{.spec.podCIDR}')
    [[ -n "$cidr" ]] || failed+=("$node: .spec.podCIDR missing")
  done < <(get_nodes)
  [[ ${#failed[@]} -eq 0 ]] || fail "$(printf '%s\n' "${failed[@]}")"
}
