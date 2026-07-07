# k8s smoke test suite

Bash/bats smoke tests against a live Kubernetes cluster (control plane HA,
dashboard, flannel, storage, node networking, pod scheduling/connectivity).

## Assumptions

- **Multi-homed nodes have exactly one ethernet interface.** On nodes with
  both wifi and ethernet, the ethernet interface is assumed to be the one
  k8s should use (bound to the node's InternalIP, and the one flannel's
  `public-ip-overwrite` annotation should point at).
- **Flannel is the CNI.** Tests check flannel-specific annotations
  (`flannel.alpha.coreos.com/public-ip-overwrite`) and behavior — they don't
  apply to clusters running Calico or another CNI.

## Install bats

```sh
# Debian/Ubuntu
sudo apt install bats

# or from source
git clone https://github.com/bats-core/bats-core.git
cd bats-core && sudo ./install.sh /usr/local
```

Tests also require `kubectl` and `jq` on `PATH`, and a working
`kubectl` context pointed at the target cluster.

## Run

```sh
./run-tests
```

Forwards args to bats, e.g. run a single file:

```sh
./run-tests tests/test_flannel.bats
```
