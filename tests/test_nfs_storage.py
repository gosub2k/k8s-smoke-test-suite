"""nfs-client storage class can provision a PVC and a pod can mount + write to it."""

from __future__ import annotations

import k8s_helpers as k
import pytest


@pytest.mark.skip("need to change this test up")
def test_nfs_pvc_provisions_and_mounts():
    pvc_name = k.unique_name("nfs-smoke")
    pod_name = k.unique_name("nfs-smoke")

    pvc = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": pvc_name},
        "spec": {
            "storageClassName": "nfs-client",
            "accessModes": ["ReadWriteMany"],
            "resources": {"requests": {"storage": "100Mi"}},
        },
    }
    pod = k.make_pod(
        pod_name,
        image="busybox",
        command=["sh", "-c", "echo nfs-smoke-ok > /data/hello && cat /data/hello"],
        pvcs={"/data": pvc_name},
    )

    k.apply(pvc)
    try:
        result = k.run_pod(pod, timeout=180)
        assert result["phase"] == "Succeeded", (
            f"NFS pod did not succeed: phase={result['phase']}\n"
            f"logs:\n{result['logs']}\nevents:\n{result['events']}"
        )
        assert "nfs-smoke-ok" in result["logs"]
    finally:
        k.delete("pvc", pvc_name)
