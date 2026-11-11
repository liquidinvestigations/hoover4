#!/bin/bash
# Test the root shrink procedure of docs/procedures/root-shrink-from-rescue.md on two loop disks.
# Run it as root on a workstation. Do not run it on a cluster host.
# The loop disks copy the layout of the public host at a smaller scale: an MBR table, partitions 1 and 2 for
# other arrays, partition 3 for a RAID1 with metadata 1.2 and an internal bitmap, and ext4 on it.
# The test shrinks the RAID1 from about 3.6 GiB to 2 GiB with the commands of the procedure.
set -eu
BASE=/var/tmp/root-shrink-test
# The test changes this local mdadm config for a short time. The rescue system of the host uses /etc/mdadm/mdadm.conf.
MDADM_CONF=/etc/mdadm.conf
MD_GIB=2
cleanup() {
  [ -f "$BASE/mdadm.conf.saved" ] && cp "$BASE/mdadm.conf.saved" "$MDADM_CONF"
  umount "$BASE/mnt" 2>/dev/null || true
  for md in $(awk '/^md/ {print $1}' /proc/mdstat 2>/dev/null); do mdadm --stop "/dev/$md" >/dev/null 2>&1 || true; done
  for l in ${L0:-} ${L1:-}; do losetup -d "$l" 2>/dev/null || true; done
  rm -rf "$BASE"
}
trap cleanup EXIT
mkdir -p "$BASE/mnt"
modprobe raid1
for i in 0 1; do
  truncate -s 4G "$BASE/disk$i.img"
  printf 'label: dos\nstart=2048, size=524288, type=fd\nsize=262144, type=fd\ntype=fd\n' | sfdisk -q "$BASE/disk$i.img"
done
L0=$(losetup -fP --show "$BASE/disk0.img"); L1=$(losetup -fP --show "$BASE/disk1.img")
# Fill the MBR boot code (bytes 0 to 439) and the gap before partition 1 (sectors 1 to 2047) as GRUB does.
for L in "$L0" "$L1"; do
  head -c 440 /dev/urandom | dd of="$L" bs=1 conv=notrunc status=none
  head -c $((2047 * 512)) /dev/urandom | dd of="$L" bs=512 seek=1 conv=notrunc status=none
done
boot_sums() { for L in "$L0" "$L1"; do head -c 440 "$L" | sha256sum; dd if="$L" bs=512 skip=1 count=2047 status=none | sha256sum; done; }
BOOT_BEFORE=$(boot_sums)
udevadm settle
mdadm --create /dev/md/rstest0 --run --level=1 --raid-devices=2 --metadata=1.2 "${L0}p1" "${L1}p1"
mdadm --create /dev/md/rstest1 --run --level=1 --raid-devices=2 --metadata=1.2 "${L0}p2" "${L1}p2"
mdadm --create /dev/md/rstest2 --run --level=1 --raid-devices=2 --metadata=1.2 --bitmap=internal --assume-clean "${L0}p3" "${L1}p3"
MD=/dev/md/rstest2
mkfs.ext4 -q "$MD"
mount "$MD" "$BASE/mnt"
for i in $(seq 1 24); do mkdir "$BASE/mnt/d$i"; head -c 20M /dev/urandom > "$BASE/mnt/d$i/data"; done
(cd "$BASE/mnt" && find . -type f -not -path './lost+found/*' | sort | xargs sha256sum) > "$BASE/sums"
umount "$BASE/mnt"

echo "== step 3: compute the sizes"
P3=${L0}p3
DATA_OFFSET=$(mdadm --examine "$P3" | awk '/Data Offset/ {print $4}')
START=$(sfdisk --dump "$L0" | awk -v p="$P3" '$1 == p {gsub(",", "", $4); print $4}')
DISK_SECTORS=$(blockdev --getsz "$L0")
MD_KIB=$((MD_GIB * 1024 * 1024))
P3_SIZE=$(( ( (DATA_OFFSET + MD_KIB * 2 + 2047) / 2048 + 1) * 2048 ))
P4_START=$((START + P3_SIZE))
P4_SIZE=$(( (DISK_SECTORS - P4_START) / 2048 * 2048 ))
echo "data offset $DATA_OFFSET, p3 start $START, new p3 size $P3_SIZE, p4 start $P4_START, p4 size $P4_SIZE"

echo "== step 4: shrink the file system, the array, and grow the file system to the array"
e2fsck -f -y "$MD"
resize2fs "$MD" $((MD_KIB * 9 / 10))K
mdadm --grow "$MD" --bitmap=none
mdadm --grow "$MD" --size="$MD_KIB"
echo "-- set the size of each member, which mdadm could not set while the array was larger"
MDNAME=$(basename "$(readlink -f "$MD")")
for F in /sys/block/$MDNAME/md/dev-*/size; do echo "$MD_KIB" > "$F"; echo "$F = $(cat "$F")"; done
for P in "${L0}p3" "${L1}p3"; do
  AVAIL=$(mdadm --examine "$P" | awk '/Avail Dev Size/ {print $5}')
  echo "$P avail $AVAIL sectors, limit $((P3_SIZE - DATA_OFFSET))"
  [ "$AVAIL" -le $((P3_SIZE - DATA_OFFSET)) ] || { echo "FAIL: member size is larger than the new partition"; exit 1; }
done
resize2fs "$MD"
e2fsck -f -n "$MD"
mdadm --detail "$MD" | grep -E "Array Size|Used Dev Size"

echo "== step 5: stop the arrays and change both partition tables"
# AUTO -all stops the udev rule from assembling arrays from one disk after its table change.
cp "$MDADM_CONF" "$BASE/mdadm.conf.saved"
echo "AUTO -all" >> "$MDADM_CONF"
mdadm --stop /dev/md/rstest2 /dev/md/rstest1 /dev/md/rstest0
for D in "$L0" "$L1"; do
  sfdisk --dump "$D" > "$BASE/$(basename "$D").before"
  sfdisk --dump "$D" | sed -E "s|^(${D}p3 : start= *[0-9]+, size= *)[0-9]+|\1${P3_SIZE}|" > "$BASE/new"
  echo "${D}p4 : start=${P4_START}, size=${P4_SIZE}, type=fd" >> "$BASE/new"
  sfdisk --wipe never --wipe-partitions never "$D" < "$BASE/new" | grep -E "^/dev|altered"
done

[ "$(boot_sums)" = "$BOOT_BEFORE" ] && echo "boot code and gap unchanged on both disks" || { echo "FAIL: boot area changed"; exit 1; }
echo "== step 6: assemble, check, and add the bitmap again"
udevadm settle
echo "-- arrays that udev assembled after the table change:"
grep -E "^md" /proc/mdstat || echo "none"
for md in $(awk '/^md/ {print $1}' /proc/mdstat); do mdadm --stop "/dev/$md"; done
mdadm --assemble /dev/md/rstest0 "${L0}p1" "${L1}p1"
mdadm --assemble /dev/md/rstest1 "${L0}p2" "${L1}p2"
mdadm --assemble "$MD" "${L0}p3" "${L1}p3"
cp "$BASE/mdadm.conf.saved" "$MDADM_CONF"; rm "$BASE/mdadm.conf.saved"
mdadm --examine "${L0}p3" | grep -E "Avail Dev Size|Used Dev Size|Data Offset"
cat /proc/mdstat | grep -A1 md
e2fsck -f -n "$MD"
mdadm --grow "$MD" --bitmap=internal
mount "$MD" "$BASE/mnt"
(cd "$BASE/mnt" && sha256sum --quiet -c "$BASE/sums") && echo "all $(wc -l < "$BASE/sums") files match"
df -h "$BASE/mnt" | tail -1
