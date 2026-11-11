# Mount the raw block volumes of a store inside its Kata guest, start the store, and unmount after it stops.
# BLOCK_MOUNTS holds "device:directory" pairs separated by spaces.
# A new TopoLVM volume is empty. The script makes an ext4 file system on a device whose first 4 KiB are all zero.
# It refuses a device that holds other data and no ext4 file system.
# BLOCK_USER, when set, is "uid:gid" for the store process and the owner of a new file system root.
# Otherwise the store starts as root and drops its own rights.
# The arguments are the store command. SIGTERM goes to the store. After it exits, the script syncs and unmounts,
# so the next start finds a clean file system.
B=/tools/busybox
musl() { /tools/musl/ld-musl-x86_64.so.1 --library-path /tools/musl "/tools/musl/$@"; }
for pair in $BLOCK_MOUNTS; do
  device=${pair%%:*} directory=${pair#*:}
  $B mkdir -p "$directory"
  # The ext2, ext3 and ext4 signature 0xEF53 is at byte 1080, little endian.
  magic=$($B dd if="$device" bs=1 skip=1080 count=2 2>/dev/null | $B od -An -tx1 | $B tr -d ' \n')
  fresh=no
  if [ "$magic" != 53ef ]; then
    if [ -n "$($B dd if="$device" bs=4096 count=1 2>/dev/null | $B tr -d '\000' | $B head -c 1)" ]; then
      echo "blockmount: $device has data and no ext4 file system" >&2; exit 1
    fi
    musl mke2fs -q -t ext4 -m 0 -E lazy_itable_init=0,lazy_journal_init=0 "$device" || { echo "blockmount: mke2fs of $device failed" >&2; exit 1; }
    fresh=yes
  fi
  $B mount -t ext4 -o noatime "$device" "$directory" || { echo "blockmount: mount of $device failed" >&2; exit 1; }
  # A grown volume reaches the guest at the next pod start. resize2fs grows the mounted file system to the device size,
  # and it changes nothing when the sizes match.
  musl resize2fs "$device" >/dev/null 2>&1 || echo "blockmount: resize2fs of $device failed" >&2
  if [ $fresh = yes ]; then
    $B rmdir "$directory/lost+found" 2>/dev/null
    if [ -n "$BLOCK_USER" ]; then $B chown "$BLOCK_USER" "$directory"; fi
    echo "blockmount: made an ext4 file system on $device"
  fi
done
# A Kata guest gives containers an open-file limit of 2^30. slapd sizes its connection tables from that limit: it fails
# at 2^30 and uses about 760 MiB at 2^20. BLOCK_NOFILE sets the cap, and the default is 1048576.
nofile=${BLOCK_NOFILE:-1048576}
if [ "$(ulimit -n)" = unlimited ] || [ "$(ulimit -n)" -gt "$nofile" ]; then ulimit -n "$nofile"; fi
if [ -n "$BLOCK_USER" ]; then set -- /tools/musl/ld-musl-x86_64.so.1 --library-path /tools/musl /tools/musl/su-exec "$BLOCK_USER" "$@"; fi
"$@" &
child=$!
trap '$B kill -TERM $child 2>/dev/null' TERM INT
trap '$B kill -QUIT $child 2>/dev/null' QUIT
wait $child
status=$?
while $B kill -0 $child 2>/dev/null; do wait $child; status=$?; done
# Children of the store, such as the Manticore Buddy, can outlive it and keep files open on the volume.
# This script is PID 1 of the container, so signal -1 reaches every other process of the container.
alive() {
  for stat in /proc/[0-9]*/stat; do
    read -r pid comm state rest < "$stat" 2>/dev/null || continue
    [ "$pid" = 1 ] || [ "$state" = Z ] || return 0
  done
  return 1
}
$B kill -TERM -1 2>/dev/null
waited=0
while alive && [ $waited -lt 20 ]; do $B sleep 0.5; waited=$((waited + 1)); done
$B kill -KILL -1 2>/dev/null
$B sync
# A read-only remount here would make the next read-write mount of the device fail with EBUSY,
# because the guest kernel keeps one superblock for each device. A lazy unmount leaves it read-write.
for pair in $BLOCK_MOUNTS; do
  directory=${pair#*:}
  $B umount "$directory" || $B umount -l "$directory"
done
exit $status
