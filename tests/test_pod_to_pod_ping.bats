#!/usr/bin/env bats
# Pod-to-pod (CNI/overlay) reachability across and within Ready nodes.
# Two busybox sleeper pods per node (a + b).
# Cross-node: a-pod on src pings a-pod on dst (overlay path).
# Same-node:  a-pod pings b-pod on the same node (intra-node CNI bridge).
load helpers

NAME_PREFIX=smoke-pingpod

setup_file() {
  readarray -t _NODES < <(ready_nodes)
  printf '%s\n' "${_NODES[@]}" > "$BATS_FILE_TMPDIR/nodes.txt"

  for node in "${_NODES[@]}"; do
    for side in a b; do
      kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${NAME_PREFIX}-${side}-${node}
spec:
  restartPolicy: Never
  nodeSelector:
    kubernetes.io/hostname: $node
  containers:
  - name: main
    image: busybox
    command: ["sleep", "3600"]
EOF
    done
  done

  > "$BATS_FILE_TMPDIR/pod_ips.txt"
  local deadline=$((SECONDS + 180))
  for node in "${_NODES[@]}"; do
    for side in a b; do
      local name="${NAME_PREFIX}-${side}-${node}"
      while [[ $SECONDS -lt $deadline ]]; do
        phase=$(kubectl get pod "$name" -o jsonpath='{.status.phase}' 2>/dev/null || true)
        ip=$(kubectl get pod "$name" -o jsonpath='{.status.podIP}' 2>/dev/null || true)
        if [[ "$phase" == "Running" && -n "$ip" ]]; then
          echo "${node}/${side} $ip" >> "$BATS_FILE_TMPDIR/pod_ips.txt"
          break
        fi
        sleep 2
      done
    done
  done
}

teardown_file() {
  [[ -f "$BATS_FILE_TMPDIR/nodes.txt" ]] || return 0
  while read -r node; do
    for side in a b; do
      kubectl delete pod "${NAME_PREFIX}-${side}-${node}" \
        --ignore-not-found=true --wait=false 2>/dev/null || true
    done
  done < "$BATS_FILE_TMPDIR/nodes.txt"
}

_pod_ip() {
  grep "^${1}/${2} " "$BATS_FILE_TMPDIR/pod_ips.txt" 2>/dev/null | awk '{print $2}'
}

@test "pod-to-pod ping across all Ready node pairs" {
  local failed=()
  readarray -t nodes < "$BATS_FILE_TMPDIR/nodes.txt"
  for src in "${nodes[@]}"; do
    for dst in "${nodes[@]}"; do
      local dst_side="a"
      [[ "$src" == "$dst" ]] && dst_side="b"

      local src_ip dst_ip
      src_ip=$(_pod_ip "$src" "a")
      dst_ip=$(_pod_ip "$dst" "$dst_side")

      [[ -n "$src_ip" ]] || { failed+=("$src/a never reached Running (CNI broken?)"); continue; }
      [[ -n "$dst_ip" ]] || { failed+=("$dst/$dst_side never reached Running"); continue; }

      run kubectl exec "${NAME_PREFIX}-a-${src}" -- ping -c 3 -W 2 "$dst_ip"
      (( status == 0 )) || failed+=("ping $src/a → $dst/$dst_side ($dst_ip) rc=$status")
    done
  done
  [[ ${#failed[@]} -eq 0 ]] || fail "$(printf '%s\n' "${failed[@]}")"
}
