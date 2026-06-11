#!/usr/bin/env bats
# Basic pod scheduling: a simple one-shot pod runs successfully on every Ready node.
load helpers

@test "simple pod runs on every Ready node" {
  local failed=()
  while read -r node; do
    name=$(unique_name "probe")
    run_one_shot "$name" "$node" "busybox" -- echo "testing...testing..."
    [[ "$PHASE" == "Succeeded" ]] || \
      failed+=("$node: phase=$PHASE
logs: $LOGS
events: $EVENTS")
  done < <(ready_nodes)
  [[ ${#failed[@]} -eq 0 ]] || fail "$(printf '%s\n' "${failed[@]}")"
}
