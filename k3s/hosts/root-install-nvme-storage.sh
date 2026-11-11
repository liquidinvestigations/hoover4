#!/bin/bash
# Make the NVMe storage tier of the public host for TopoLVM. Run it as root on that host.
# Partition 4 of each NVMe disk becomes the RAID1 /dev/md3, as for the other partitions of the host.
# The volume group tier-nvme on /dev/md3 is the TopoLVM device class nvme.
# A second run changes nothing. The first resync runs in the background, and the array is usable during it.
# The partitions come from the root shrink procedure in docs/procedures/root-shrink-from-rescue.md.
# Usage: root-install-nvme-storage.sh [--dry-run]. --dry-run shows the changes and changes nothing.
set -euo pipefail
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
MEMBERS=(/dev/nvme0n1p4 /dev/nvme1n1p4)
MD=/dev/md3
VG=tier-nvme
MDADM_CONF=/etc/mdadm/mdadm.conf
# do_change <command>: run the command, or show it in a dry run.
do_change() {
  echo "  \$ $*"
  [ "$DRY" = 1 ] || "$@"
}

if [ -e "$MD" ]; then
  echo "  $MD exists"
else
  for p in "${MEMBERS[@]}"; do
    # Stop if a partition holds a file system, RAID or LVM signature.
    if [ -n "$(wipefs -n "$p")" ]; then echo "ERROR: $p has a signature. Inspect it first." >&2; exit 1; fi
  done
  do_change mdadm --create "$MD" --run --level=1 --raid-devices=2 --metadata=1.2 --bitmap=internal --name=3 "${MEMBERS[@]}"
fi
if [ -e "$MD" ]; then
  UUID=$(mdadm --detail "$MD" | awk '/UUID :/ {print $3}')
  if grep -q "$UUID" "$MDADM_CONF"; then
    echo "  $MDADM_CONF has the array $UUID"
  else
    echo "  \$ echo 'ARRAY /dev/md/3  metadata=1.2 UUID=$UUID' >> $MDADM_CONF"
    [ "$DRY" = 1 ] || echo "ARRAY /dev/md/3  metadata=1.2 UUID=$UUID" >> "$MDADM_CONF"
    # The initramfs holds a copy of mdadm.conf. The array then keeps its name at boot.
    do_change update-initramfs -u
  fi
else
  echo "  \$ echo 'ARRAY /dev/md/3  metadata=1.2 UUID=<new>' >> $MDADM_CONF; update-initramfs -u"
fi
if pvs "$MD" >/dev/null 2>&1; then echo "  $MD is a physical volume"; else do_change pvcreate "$MD"; fi
if vgs "$VG" >/dev/null 2>&1; then echo "  the volume group $VG exists"; else do_change vgcreate "$VG" "$MD"; fi
if [ "$DRY" = 1 ]; then
  echo "== dry run, no change made"
else
  grep -A2 "^md3" /proc/mdstat
  vgs "$VG"
fi
