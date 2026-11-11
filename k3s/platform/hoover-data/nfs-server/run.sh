#!/bin/sh
# Serve the Hoover data directories of one node with NFS version 4 over TCP port 2049.
# /config/exports is the export table that install-hoover-data.py writes. /exports is the data root of the node and the
# NFS root, with one folder for each zone and the folder extra of the extra directories.
# Every 10 seconds the script creates <zone>/testdata and <zone>/uploads for each Hoover zone
# namespace, so a zone that the zone runner creates has its folders before its pods mount them.
# At SIGTERM the server stops, so the clients wait for the next server and its grace period.
set -eu
modprobe nfsd
mount -t nfsd nfsd /proc/fs/nfsd
cp /config/exports /etc/exports
rpcbind -w
exportfs -ra
rpc.mountd --no-nfs-version 3 --no-udp
rpc.nfsd --no-nfs-version 3 --no-udp 16
echo "nfs: serving $(exportfs | tr -s ' \n' ' ')"
stop() {
  rpc.nfsd 0
  exportfs -ua
  exit 0
}
trap stop TERM INT
api=https://kubernetes.default.svc
account=/var/run/secrets/kubernetes.io/serviceaccount
while :; do
  if zones=$(curl -sf --cacert $account/ca.crt -H "Authorization: Bearer $(cat $account/token)" \
      "$api/api/v1/namespaces?labelSelector=hoover.dev%2Fzone%3Dtrue" | jq -r '.items[].metadata.name | select(startswith("hoover-")) | ltrimstr("hoover-")'); then
    for zone in $zones; do
      case $zone in zone-*) mkdir -p "/exports/$zone/testdata" "/exports/$zone/uploads" ;; esac
    done
  fi
  sleep 10 &
  wait $!
done
