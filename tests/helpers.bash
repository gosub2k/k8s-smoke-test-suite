#!/usr/bin/env bash
# Shared helpers for bats smoke tests.  Load with:  load helpers

# -- kubectl ------------------------------------------------------------------

kubectl_json() { kubectl "$@" -o json; }

# -- nodes --------------------------------------------------------------------

ready_nodes() {
  kubectl get nodes -o json | jq -r '
    .items[] |
    select(.status.conditions[] | select(.type == "Ready" and .status == "True")) |
    .metadata.name'
}

get_nodes() {
  kubectl get nodes -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n'
}

node_internal_ip() {
  kubectl get node "$1" -o jsonpath='{.status.addresses[?(@.type=="InternalIP")].address}'
}

# -- pod helpers --------------------------------------------------------------

unique_name() {
  printf '%s-%s' "$1" "$(tr -dc 'a-f0-9' < /dev/urandom | head -c 8)"
}

wait_pod_phase() {
  local name="$1" timeout="${2:-120}"
  local deadline=$((SECONDS + timeout)) phase="?"
  while [[ $SECONDS -lt $deadline ]]; do
    phase=$(kubectl get pod "$name" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    [[ "$phase" =~ ^(Succeeded|Failed)$ ]] && break
    sleep 2
  done
  printf '%s' "$phase"
}

wait_pod_running() {
  local name="$1" timeout="${2:-180}"
  local deadline=$((SECONDS + timeout))
  while [[ $SECONDS -lt $deadline ]]; do
    phase=$(kubectl get pod "$name" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    [[ "$phase" == "Running" ]] && return 0
    [[ "$phase" == "Failed" ]] && return 1
    sleep 2
  done
  return 1
}

delete_pod() {
  kubectl delete pod "$1" --ignore-not-found=true --wait=false 2>/dev/null || true
}

# one_shot_pod_json <name> <node> <image> [--host-network] -- <cmd...>
# Builds a one-shot Pod manifest JSON (restartPolicy: Never).
one_shot_pod_json() {
  local name="$1" node="$2" image="$3"
  shift 3
  local host_network=false
  [[ "${1:-}" == "--host-network" ]] && { host_network=true; shift; }
  [[ "${1:-}" == "--" ]] && shift
  local cmd_json
  cmd_json=$(printf '%s\n' "$@" | jq -R . | jq -sc .)
  jq -n \
    --arg   name     "$name"  \
    --arg   node     "$node"  \
    --arg   image    "$image" \
    --argjson hostNet "$host_network" \
    --argjson cmd    "$cmd_json" \
    '{apiVersion:"v1",kind:"Pod",metadata:{name:$name},
      spec:{restartPolicy:"Never",hostNetwork:$hostNet,
            nodeSelector:{"kubernetes.io/hostname":$node},
            containers:[{name:"main",image:$image,command:$cmd}]}}'
}

# run_one_shot <name> <node> <image> [--host-network] -- <cmd...>
# Applies the pod, waits for terminal phase, sets $PHASE $LOGS $EVENTS, cleans up.
run_one_shot() {
  local spec
  spec=$(one_shot_pod_json "$@")
  local name; name=$(jq -r '.metadata.name' <<< "$spec")
  printf '%s' "$spec" | kubectl apply -f - >/dev/null
  PHASE=$(wait_pod_phase "$name")
  LOGS=$(kubectl logs "$name" 2>/dev/null || true)
  EVENTS=$(kubectl get events --field-selector="involvedObject.name=$name" \
           --no-headers 2>/dev/null || true)
  delete_pod "$name"
}

# -- interface probing (hostNetwork pod) --------------------------------------

iface_kind() {
  case "$1" in
    en[opsx]*|eth[0-9]*) echo "ethernet" ;;
    wl*)                  echo "wifi"     ;;
    *)                    echo "other"    ;;
  esac
}

# list_ipv4_interfaces <node>  →  "iface ip" per line (prefix stripped)
# Returns 1 if the probe pod fails.
list_ipv4_interfaces() {
  local node="$1" name
  name=$(unique_name "iface-probe")
  local cmd='ip -o addr show | awk '"'"'$3=="inet"{print $2,$4}'"'"
  local spec
  spec=$(one_shot_pod_json "$name" "$node" "busybox" --host-network -- sh -c "$cmd")
  printf '%s' "$spec" | kubectl apply -f - >/dev/null
  local phase
  phase=$(wait_pod_phase "$name" 60)
  local logs=""
  [[ "$phase" == "Succeeded" ]] && logs=$(kubectl logs "$name" 2>/dev/null || true)
  delete_pod "$name"
  [[ "$phase" == "Succeeded" ]] || return 1
  while IFS=" " read -r iface cidr; do
    [[ -n "$iface" ]] && printf '%s %s\n' "$iface" "${cidr%%/*}"
  done <<< "$logs"
}

# -- ssh ----------------------------------------------------------------------

ssh_node() {
  local host="$1"; shift
  ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "$host" "$@"
}
