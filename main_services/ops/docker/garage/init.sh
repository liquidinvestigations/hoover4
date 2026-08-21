#!/bin/sh
# Turn a blank Garage node into a usable single-node cluster: assign a layout, import
# the S3 key, create the system bucket, grant the key.
#
# Every step is idempotent and every step is checked before it is taken, because this
# runs on EVERY deploy, not only the first. A bootstrap that only works against a blank
# node breaks the next `./deploy` instead of the first one, which is the harder failure
# to recognise.
set -eu

ADMIN="http://garage:3903"
ZONE="${GARAGE_ZONE:-dc1}"
CAPACITY="${GARAGE_CAPACITY:-300G}"
# Only the system bucket is bootstrapped. There is a bucket per collection and the
# application creates each one with its collection — which is why the key is granted
# --create-bucket below rather than being handed a fixed list.
BUCKET="${S3_SYSTEM_BUCKET:-hoover4-system}"
KEY_NAME="${S3_KEY_NAME:-hoover4}"

say() { echo "garage-init: $*"; }

status() {
    curl -s -H "Authorization: Bearer $GARAGE_ADMIN_TOKEN" "$ADMIN/v2/GetClusterStatus"
}

# 1) Wait for the admin API to name the node.
#
#    NOT for `/health` to return 200: that endpoint reports 503 "Quorum is not available
#    for some/all partitions" until a layout is assigned, and assigning the layout is
#    this script's own first job -- waiting for it deadlocks on a node that has never
#    been bootstrapped. The node id is both the real readiness signal and the next
#    thing needed, so poll for that instead. Bounded, and loud on expiry: a bootstrap
#    that hangs forever holds up every service depending on it and says nothing.
i=0
NODE=""
while [ -z "$NODE" ] || [ "$NODE" = "null" ]; do
    NODE=$(status | jq -r '.nodes[0].id // empty' 2>/dev/null)
    [ -n "$NODE" ] && [ "$NODE" != "null" ] && break
    i=$((i + 1))
    if [ "$i" -ge 90 ]; then
        say "garage's admin API never named a node at $ADMIN/v2/GetClusterStatus"
        say "last response: $(status | head -c 200)"
        exit 1
    fi
    sleep 1
done
say "garage answers; node $NODE"
export GARAGE_RPC_HOST="$NODE@garage:3901"

# 2) Layout. `.nodes[0].role` is null until a layout is applied, which is the exact
#    idempotency test -- `layout assign` on an already-assigned node is not a no-op.
ROLE=$(status | jq -r '.nodes[0].role')
if [ "$ROLE" = "null" ]; then
    say "assigning layout: zone=$ZONE capacity=$CAPACITY"
    garage layout assign -z "$ZONE" -c "$CAPACITY" "$NODE"
    garage layout apply --version 1
else
    say "layout already assigned"
fi

# 3) The S3 key. `key import` fails if the id already exists, so ask first.
if garage key info "$S3_ACCESS_KEY" >/dev/null 2>&1; then
    say "key $S3_ACCESS_KEY already present"
else
    say "importing key $S3_ACCESS_KEY"
    garage key import --yes "$S3_ACCESS_KEY" "$S3_SECRET_KEY" -n "$KEY_NAME"
fi
# Unconditional: granting a permission that is already granted is a no-op, and the
# clients call make_bucket themselves when the bucket is missing.
garage key allow --create-bucket "$S3_ACCESS_KEY"

# 4) The system bucket and its grant. Per-collection buckets are created at runtime.
if garage bucket info "$BUCKET" >/dev/null 2>&1; then
    say "bucket $BUCKET already present"
else
    say "creating bucket $BUCKET"
    garage bucket create "$BUCKET"
fi
garage bucket allow --read --write --owner "$BUCKET" --key "$S3_ACCESS_KEY"

say "ready: bucket=$BUCKET key=$S3_ACCESS_KEY"
