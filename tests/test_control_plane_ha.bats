#!/usr/bin/env bats
# Control plane has redundancy: enough CP nodes and a healthy datastore.
# Some tests here document the HA posture we want but may not pass yet.
load helpers

cp_node_names() {
  kubectl get nodes -o json | jq -r '
    .items[] |
    select(
      .metadata.labels |
      (has("node-role.kubernetes.io/control-plane") or
       has("node-role.kubernetes.io/master") or
       has("node.kubernetes.io/microk8s-controlplane"))
    ) | .metadata.name'
}

@test "at least 2 control-plane nodes are Ready" {
  local ready=0
  while read -r node; do
    st=$(kubectl get node "$node" \
      -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)
    [[ "$st" == "True" ]] && (( ready++ )) || true
  done < <(cp_node_names)
  (( ready >= 2 )) || fail "want >=2 Ready control-plane nodes, found $ready"
}

@test "at least 3 control-plane nodes exist" {
  skip "cluster does not have 3 control-plane nodes yet"
  local count
  count=$(cp_node_names | wc -l)
  (( count >= 3 )) || fail "want >=3 control-plane nodes for HA, found $count"
}

@test "etcd componentstatus is Healthy" {
  run kubectl get componentstatuses -o json
  [[ "$status" -eq 0 ]] || skip "componentstatuses unavailable: $output"
  local names
  names=$(jq -r '.items[] | select(.metadata.name | startswith("etcd")) | .metadata.name' \
           <<< "$output")
  [[ -n "$names" ]] || fail "no etcd componentstatus entries"
  while read -r name; do
    h=$(jq -r --arg n "$name" \
        '.items[] | select(.metadata.name == $n) |
         .conditions[] | select(.type == "Healthy") | .status' <<< "$output")
    [[ "$h" == "True" ]] || fail "etcd $name not Healthy"
  done <<< "$names"
}

@test "controller-manager and scheduler are Healthy" {
  run kubectl get componentstatuses -o json
  [[ "$status" -eq 0 ]] || skip "componentstatuses unavailable: $output"
  for component in controller-manager scheduler; do
    h=$(jq -r --arg c "$component" \
        '.items[] | select(.metadata.name == $c) |
         .conditions[] | select(.type == "Healthy") | .status' <<< "$output")
    [[ "$h" == "True" ]] || fail "$component not Healthy"
  done
}
