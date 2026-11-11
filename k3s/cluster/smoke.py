#!/usr/bin/env python3
"""Smoke test of the minimal cluster. Run it with kubectl and the admin kubeconfig in KUBECONFIG.

The test uses the namespace smoke and deletes it at the end. It checks these points on every node.
  network   A runc pod serves a 4 MiB file. Every other pod downloads it and compares the checksum.
            This passes the VXLAN traffic over wg0, so it also shows MTU faults. DNS and a ClusterIP Service.
  runtimes  A gVisor pod and a Kata pod. Each one prints its kernel and downloads the file from another node.
  storage   For each storage tier of each node (label storage.tier/<tier>): a <tier>-ext4 volume in a runc pod
            and in a gVisor pod, and a <tier>-block volume in a Kata pod. After the delete, the TopoLVM
            LogicalVolumes must go.
"""
import json
import subprocess
import sys
import time

NS = "smoke"
IMAGE = "busybox:1.37.0"
RESULTS = []


def kubectl(*args, input_text=None, check=True):
    proc = subprocess.run(["kubectl", *args], input=input_text, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)}: {proc.stdout.strip()}")
    return proc.stdout


def apply(objects):
    kubectl("apply", "-f", "-", input_text=json.dumps({"apiVersion": "v1", "kind": "List", "items": objects}))


def sh(pod, script, timeout=120):
    proc = subprocess.run(["kubectl", "-n", NS, "exec", pod, "--", "sh", "-c", script], stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, timeout=timeout)
    return proc.returncode, proc.stdout.strip()


def record(check, node, ok, detail):
    RESULTS.append((check, node, "pass" if ok else "FAIL", detail))
    print(f"{'pass' if ok else 'FAIL'}  {check:<22} {node:<12} {detail}", flush=True)


def pod(name, node, runtime=None, command="sleep 3600", volumes=None):
    spec = {
        "nodeSelector": {"kubernetes.io/hostname": node},
        "terminationGracePeriodSeconds": 1,
        "containers": [{"name": "main", "image": IMAGE, "command": ["sh", "-c", command],
                        "resources": {"limits": {"memory": "128Mi", "cpu": "250m"}}}],
    }
    if runtime:
        spec["runtimeClassName"] = runtime
    for v in volumes or []:
        spec.setdefault("volumes", []).append({"name": v["name"], "persistentVolumeClaim": {"claimName": v["name"]}})
        key, entry = ("volumeDevices", {"devicePath": v["path"]}) if v["block"] else ("volumeMounts", {"mountPath": v["path"]})
        spec["containers"][0].setdefault(key, []).append({"name": v["name"], **entry})
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": NS, "labels": {"app": name}}, "spec": spec}


def pvc(name, storage_class, block=False):
    return {"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": name, "namespace": NS},
            "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": storage_class,
                     "volumeMode": "Block" if block else "Filesystem", "resources": {"requests": {"storage": "1Gi"}}}}


def wait_ready(names, timeout=600):
    deadline = time.time() + timeout
    pending = set(names)
    while pending and time.time() < deadline:
        items = json.loads(kubectl("-n", NS, "get", "pods", "-o", "json"))["items"]
        for item in items:
            ready = any(c["type"] == "Ready" and c["status"] == "True" for c in item["status"].get("conditions", []))
            if ready:
                pending.discard(item["metadata"]["name"])
        time.sleep(3)
    return pending


def main():
    nodes = json.loads(kubectl("get", "nodes", "-o", "json"))["items"]
    names = [n["metadata"]["name"] for n in nodes]
    storage = [(n["metadata"]["name"], key.split("/", 1)[1]) for n in nodes for key, value in n["metadata"]["labels"].items()
               if key.startswith("storage.tier/") and value == "true"]
    kubectl("delete", "namespace", NS, "--ignore-not-found", "--wait=true")
    kubectl("create", "namespace", NS)
    serve = "mkdir -p /www && head -c 4194304 /dev/urandom > /www/big && md5sum /www/big > /www/big.md5 && httpd -f -p 8080 -h /www"
    objects = []
    for node in names:
        objects += [pod(f"net-{node}", node, command=serve), pod(f"gvisor-{node}", node, "gvisor"), pod(f"kata-{node}", node, "kata")]
    for node, tier in storage:
        for kind, sc, block, runtime, path in [("ext4", f"{tier}-ext4", False, None, "/data"), ("gvext4", f"{tier}-ext4", False, "gvisor", "/data"),
                                                ("block", f"{tier}-block", True, "kata", "/dev/xvdb")]:
            name = f"vol-{kind}-{node}"
            objects += [pvc(name, sc, block), pod(name, node, runtime, volumes=[{"name": name, "path": path, "block": block}])]
    objects.append({"apiVersion": "v1", "kind": "Service", "metadata": {"name": "web", "namespace": NS},
                    "spec": {"selector": {"app": f"net-{names[-1]}"}, "ports": [{"port": 80, "targetPort": 8080}]}})
    apply(objects)
    pods = [o["metadata"]["name"] for o in objects if o["kind"] == "Pod"]
    started = time.time()
    pending = wait_ready(pods)
    print(f"pods ready after {time.time() - started:.0f} s", flush=True)
    for name in sorted(pending):
        events = kubectl("-n", NS, "get", "events", "--field-selector", f"involvedObject.name={name}", "-o",
                         "custom-columns=REASON:.reason,MESSAGE:.message", "--no-headers", check=False)
        record("pod start", name, False, " | ".join(events.strip().splitlines()[-3:]))

    ips = {}
    for item in json.loads(kubectl("-n", NS, "get", "pods", "-o", "json"))["items"]:
        ips[item["metadata"]["name"]] = item["status"].get("podIP")
    sums = {}
    for node in names:
        if f"net-{node}" not in pending:
            sums[node] = sh(f"net-{node}", "cut -d' ' -f1 /www/big.md5")[1]

    # Network between all nodes, from runc, gVisor and Kata pods.
    for node in names:
        for client in [f"net-{node}", f"gvisor-{node}", f"kata-{node}"]:
            if client in pending:
                continue
            for target in names:
                if target == node or target not in sums:
                    continue
                start = time.time()
                code, out = sh(client, f"wget -q -T 20 -O - http://{ips[f'net-{target}']}:8080/big | md5sum | cut -d' ' -f1")
                record(f"http {client.split('-')[0]}", f"{node}->{target}", code == 0 and out == sums[target],
                       f"{time.time() - start:.1f} s" if out == sums[target] else out[-120:])
            code, out = sh(client, "nslookup kubernetes.default.svc.cluster.local 2>&1 | grep -A1 '^Name:' | tr '\\n' ' '")
            record(f"dns {client.split('-')[0]}", node, "10.43.0.1" in out, out[-80:])
            code, out = sh(client, "wget -q -T 20 -O - http://web.smoke.svc.cluster.local/big.md5 | cut -c1-12")
            record(f"service {client.split('-')[0]}", node, code == 0 and len(out) == 12, out[-80:])

    # Runtime identity.
    for node in names:
        for runtime in ["gvisor", "kata"]:
            name = f"{runtime}-{node}"
            if name in pending:
                continue
            code, out = sh(name, "uname -r; dmesg 2>/dev/null | head -1 | cut -c1-60")
            # gVisor reports its own kernel version. Kata reports the guest kernel, not the host kernel.
            first = out.splitlines()[0] if out else ""
            ok = code == 0 and ("gvisor" in first if runtime == "gvisor" else "el9" not in first and "deb13" not in first)
            record(f"runtime {runtime}", node, ok, " / ".join(out.splitlines()))

    # Volumes.
    for node, tier in storage:
        for kind in ["ext4", "gvext4"]:
            name = f"vol-{kind}-{node}"
            if name in pending:
                continue
            code, out = sh(name, "head -c 67108864 /dev/urandom > /data/f && sync && md5sum /data/f | cut -c1-8 && df -h /data | tail -1")
            record(f"volume {tier} {kind}", node, code == 0, " / ".join(out.splitlines()))
        name = f"vol-block-{node}"
        if name not in pending:
            code, out = sh(name, "ls -l /dev/xvdb && head -c 67108864 /dev/urandom > /tmp/f && dd if=/tmp/f of=/dev/xvdb bs=1M conv=fsync 2>/dev/null"
                                 " && dd if=/dev/xvdb bs=1M count=64 2>/dev/null | md5sum | cut -c1-8 && md5sum /tmp/f | cut -c1-8")
            lines = out.splitlines()
            record(f"volume {tier} block kata", node, code == 0 and len(lines) >= 3 and lines[-1] == lines[-2], " / ".join(lines)[-160:])
    capacity = kubectl("get", "csistoragecapacities", "-A", "-o", "custom-columns=NODE:.nodeTopology.matchLabels,CAP:.capacity", "--no-headers")
    print("TopoLVM capacity:\n" + capacity, flush=True)

    # Other namespaces, for example the zones and the registry, keep their volumes. A LogicalVolume has the name of its
    # PersistentVolume, so the check follows the volumes of the claims in its own namespace.
    own = {c["spec"].get("volumeName") for c in json.loads(kubectl("-n", NS, "get", "pvc", "-o", "json"))["items"]} - {None}
    kubectl("delete", "namespace", NS, "--wait=true", "--timeout=300s", check=False)
    deadline = time.time() + 180
    while time.time() < deadline:
        left = own & {lv["metadata"]["name"] for lv in json.loads(kubectl("get", "logicalvolumes.topolvm.io", "-o", "json"))["items"]}
        if not left:
            break
        time.sleep(5)
    record("volume delete", "all", bool(own) and not left, f"{len(own)} LogicalVolumes of the check, {len(left)} after the delete")
    failed = [r for r in RESULTS if r[2] == "FAIL"]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
