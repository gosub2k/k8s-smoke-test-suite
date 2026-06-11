#!/usr/bin/env bats
# kubernetes-dashboard is deployed, running, and reachable on its NodePort.
load helpers

NS=kube-system
NAME=kubernetes-dashboard

@test "kubernetes-dashboard deployment exists" {
  run kubectl get deployment "$NAME" -n "$NS"
  [ "$status" -eq 0 ]
}

@test "kubernetes-dashboard has at least 1 available replica" {
  run kubectl get deployment "$NAME" -n "$NS" -o json
  [ "$status" -eq 0 ]
  available=$(jq -r '.status.availableReplicas // 0' <<< "$output")
  (( available >= 1 )) || fail "want >=1 availableReplicas, got $available"
}

@test "kubernetes-dashboard NodePort is reachable" {
  run kubectl get svc "$NAME" -n "$NS" -o json
  [ "$status" -eq 0 ]
  svc_type=$(jq -r '.spec.type' <<< "$output")
  [[ "$svc_type" == "NodePort" ]] || fail "service is $svc_type, expected NodePort"
  node_port=$(jq -r '[.spec.ports[] | select(.nodePort) | .nodePort] | first // empty' <<< "$output")
  [[ -n "$node_port" ]] || fail "no nodePort on $NAME service"

  readarray -t nodes < <(ready_nodes)
  (( ${#nodes[@]} > 0 )) || skip "no Ready nodes to probe"
  target="${nodes[0]}"
  target_ip=$(node_internal_ip "$target")

  name=$(unique_name "dash-probe")
  run_one_shot "$name" "$target" "busybox" --host-network -- \
    sh -c "nc -z -w 3 $target_ip $node_port"
  [[ "$PHASE" == "Succeeded" ]] || \
    fail "NodePort $target_ip:$node_port not reachable: phase=$PHASE
logs:
$LOGS
events:
$EVENTS"
}
