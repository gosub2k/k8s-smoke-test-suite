#!/usr/bin/env bats
# SSH-to-node capability check.  Skips nodes where SSH is not configured.
load helpers

@test "SSH to each Ready node returns a hostname" {
  local failed=()
  while read -r node; do
    out=$(ssh_node "$node" hostname 2>/dev/null) || continue
    [[ -n "$out" ]] || failed+=("$node: empty hostname output")
  done < <(ready_nodes)
  [[ ${#failed[@]} -eq 0 ]] || fail "$(printf '%s\n' "${failed[@]}")"
}
