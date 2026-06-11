#!/usr/bin/env bats
# Nodes with both ethernet and wifi must bind their InternalIP to ethernet.
load helpers

@test "nodes with both ethernet and wifi bind InternalIP to ethernet" {
  local failed=()
  while read -r node; do
    internal_ip=$(node_internal_ip "$node")
    [[ -n "$internal_ip" ]] || { failed+=("$node: no InternalIP"); continue; }

    local eth=() wifi=() bound=""
    while IFS=" " read -r iface ip; do
      case $(iface_kind "$iface") in
        ethernet) eth+=("$iface"); [[ "$ip" == "$internal_ip" ]] && bound="$iface" ;;
        wifi)     wifi+=("$iface") ;;
      esac
    done < <(list_ipv4_interfaces "$node" 2>/dev/null || true)

    [[ ${#eth[@]} -gt 0 && ${#wifi[@]} -gt 0 ]] || continue
    [[ -n "$bound" ]] || \
      failed+=("$node: InternalIP $internal_ip not on ethernet (eth=${eth[*]}, wifi=${wifi[*]})")
  done < <(ready_nodes)
  [[ ${#failed[@]} -eq 0 ]] || fail "$(printf '%s\n' "${failed[@]}")"
}
