#!/bin/bash
# Test the storage step of root-install.py on a loop device. Run it as root on a workstation. Do not run it on a cluster host.
# The test makes an 8 GiB disk image with one ext4 partition and 1.2 GiB of files in 48 folders.
# It shrinks the file system to 3 GiB, then compares the file checksums and shows the new table.
# It removes the loop device, the volume group and the image at the end.
set -eu
SCRIPT=$(realpath "$(dirname "$0")/root-install.py")
BASE=/var/tmp/root-install-test
VG=ritest-tier
cleanup() {
  for m in "$BASE/kubelet" "$BASE/rancher" "$BASE/opt" "$BASE/storage"; do umount "$m" 2>/dev/null || true; done
  vgremove -y "$VG" >/dev/null 2>&1 || true
  [ -n "${LOOP:-}" ] && { pvremove -y "${LOOP}p2" >/dev/null 2>&1 || true; losetup -d "$LOOP"; }
  rm -rf "$BASE"
}
trap cleanup EXIT
mkdir -p "$BASE"/{storage,opt,rancher,kubelet}
truncate -s 8G "$BASE/disk.img"
echo "label: gpt" | sfdisk -q "$BASE/disk.img"
echo "start=2048, type=0FC63DAF-8483-4772-8E79-3D69D8477DE4" | sfdisk -q --append "$BASE/disk.img"
LOOP=$(losetup -fP --show "$BASE/disk.img")
mkfs.ext4 -q "${LOOP}p1"
printf '%s %s ext4 defaults 0 0\n%s %s none bind 0 0\n' "${LOOP}p1" "$BASE/storage" "$BASE/storage/opt" "$BASE/opt" > "$BASE/fstab"
mount "${LOOP}p1" "$BASE/storage"
mkdir "$BASE/storage/opt"
mount --bind "$BASE/storage/opt" "$BASE/opt"
for i in $(seq 1 48); do
  mkdir "$BASE/storage/d$i"
  head -c 25M /dev/urandom > "$BASE/storage/d$i/data"
done
echo kept > "$BASE/opt/file"
(cd "$BASE/storage" && find . -type f -not -path './lost+found/*' | sort | xargs sha256sum) > "$BASE/sums"
echo "== highest data block before the shrink, in 4 KiB blocks (3 GiB is block 786432)"
for i in $(seq 1 48); do filefrag -e "$BASE/storage/d$i/data" | awk '$1 ~ /^[0-9]+:$/ {print $5}'; done | tr -d . | sort -n | tail -1

run() {
  python3 -I -B - "$SCRIPT" "$LOOP" "$BASE" "$VG" "$1" <<'EOF'
import importlib.util, os, sys
path, loop, base, vg, mode = sys.argv[1:6]
spec = importlib.util.spec_from_file_location("ri", path)
ri = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ri)
# The test host is an on-prem host. The source file has no host until write-host-copies.py fills it.
ri.THIS, ri.HOSTS = "loop-test", {"loop-test": {"onprem": True}}
ri.DISK, ri.PART, ri.NEW_PART = loop, loop + "p1", loop + "p2"
ri.STORAGE, ri.BIND_MOUNTS, ri.STORAGE_GIB, ri.VG = base + "/storage", [base + "/opt"], 3, vg
ri.K3S_VOLUMES = [("rancher", "512M", base + "/rancher"), ("kubelet", "256M", base + "/kubelet")]
ri.TABLE_BACKUP, ri.FSTAB, ri.DRY = base + "/table-before", base + "/fstab", mode == "dry"
real = ri.change
def change(cmd, **kw):
    if cmd[:2] == ["systemctl", "daemon-reload"]:
        return ""
    if cmd[0] == "mount" and len(cmd) == 2:
        cmd = ["mount", "--fstab", ri.FSTAB, cmd[1]]
    return real(cmd, **kw)
ri.change = change
ri.step_storage(True)
EOF
}
echo "== dry run"; run dry
echo "== run"; run real
echo "== second run"; run real
echo "== checksums"
(cd "$BASE/storage" && sha256sum --quiet -c "$BASE/sums") && echo "all $(wc -l < "$BASE/sums") files match"
cat "$BASE/opt/file"
sfdisk --dump "$LOOP" | tail -2
df -h "$BASE/storage" "$BASE/rancher" "$BASE/kubelet" | tail -3
cat "$BASE/fstab"
