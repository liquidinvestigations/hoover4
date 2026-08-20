#!/bin/sh
# Turn a blank Garage node into a usable single-node cluster: assign a layout, import
# the S3 key, create the bucket, grant the key.
#
# Every step is idempotent and every step is checked before it is taken, because this
# runs on EVERY deploy, not only the first. A bootstrap that only works against a blank
# node breaks the next `./deploy` instead of the first one, which is the harder failure
# to recognise.
set -eu

ADMIN="http://garage:3903"
ZONE="${GARAGE_ZONE:-dc1}"
CAPACITY="${GARAGE_CAPACITY:-300G}"
BUCKET="${S3_BUCKET:-hoover4-blobs}"
KEY_NAME="${S3_KEY_NAME:-hoover4}"

say() { echo "garage-init: $*"; }

# 1) Wait for the daemon. Bounded, and loud on expiry -- a bootstrap that hangs forever
#    holds up every service that depends on it and says nothing about why.
i=0
until curl -sf "$ADMIN/health" >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "$i" -ge 60 ]; then
        say "garage did not become healthy at $ADMIN/health after 60s"
        exit 1
    fi
    sleep 1
done
say "garage is healthy"

status() {
    curl -sf -H "Authorization: Bearer $GARAGE_ADMIN_TOKEN" "$ADMIN/v2/GetClusterStatus"
}

NODE=$(status | jq -r '.nodes[0].id')
if [ -z "$NODE" ] || [ "$NODE" = "null" ]; then
    say "could not read the node id from $ADMIN/v2/GetClusterStatus"
    exit 1
fi
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

# 4) The bucket and its grant.
if garage bucket info "$BUCKET" >/dev/null 2>&1; then
    say "bucket $BUCKET already present"
else
    say "creating bucket $BUCKET"
    garage bucket create "$BUCKET"
fi
garage bucket allow --read --write --owner "$BUCKET" --key "$S3_ACCESS_KEY"

say "ready: bucket=$BUCKET key=$S3_ACCESS_KEY"
