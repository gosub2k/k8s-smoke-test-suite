#!/usr/bin/env bats
# NodePort cross-node reachability via an nginx Deployment + Service.
# A NodePort must answer on every node's IP regardless of where the backend pod lives.
load helpers

NAME=smoke-nginx
NODEPORT=30888

setup_file() {
  kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $NAME
spec:
  replicas: 1
  selector:
    matchLabels:
      app: $NAME
  template:
    metadata:
      labels:
        app: $NAME
    spec:
      containers:
      - name: nginx
        image: nginx:alpine
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: $NAME
spec:
  type: NodePort
  selector:
    app: $NAME
  ports:
  - port: 80
    targetPort: 80
    nodePort: $NODEPORT
EOF
  local deadline=$((SECONDS + 180))
  while [[ $SECONDS -lt $deadline ]]; do
    avail=$(kubectl get deployment "$NAME" -o jsonpath='{.status.availableReplicas}' 2>/dev/null || echo 0)
    (( ${avail:-0} >= 1 )) && return 0
    sleep 2
  done
  return 1
}

teardown_file() {
  kubectl delete svc,deployment "$NAME" --ignore-not-found=true --wait=false 2>/dev/null || true
}

_looks_like_nginx() { [[ "$1" =~ [Nn]ginx|[Ww]elcome ]]; }

@test "NodePort is reachable from local shell on every Ready node" {
  command -v wget >/dev/null || skip "wget not installed locally"
  local failed=()
  while read -r node; do
    ip=$(node_internal_ip "$node")
    url="http://$ip:$NODEPORT/"
    body=$(wget -qO- --timeout=5 --tries=1 "$url" 2>/dev/null) || {
      failed+=("$node: wget $url failed")
      continue
    }
    _looks_like_nginx "$body" || failed+=("$node: unexpected body from $url")
  done < <(ready_nodes)
  [[ ${#failed[@]} -eq 0 ]] || fail "$(printf '%s\n' "${failed[@]}")"
}

@test "NodePort is reachable via SSH from each node to its peers" {
  local failed=()
  readarray -t nodes < <(ready_nodes)
  for src in "${nodes[@]}"; do
    for dst in "${nodes[@]}"; do
      [[ "$src" != "$dst" ]] || continue
      dst_ip=$(node_internal_ip "$dst")
      url="http://$dst_ip:$NODEPORT/"
      err_file=$(mktemp)
      body=$(ssh_node "$src" "wget -qO- --timeout=5 --tries=1 $url" 2>"$err_file") || {
        err=$(cat "$err_file"); rm -f "$err_file"
        [[ "$err" =~ "Permission denied"|"Host key"|"Could not resolve" ]] && continue
        failed+=("$src→$dst: wget $url failed: $err")
        continue
      }
      rm -f "$err_file"
      _looks_like_nginx "$body" || failed+=("$src→$dst: unexpected body from $url")
    done
  done
  [[ ${#failed[@]} -eq 0 ]] || fail "$(printf '%s\n' "${failed[@]}")"
}
