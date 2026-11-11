#!/usr/bin/env bash
# Set the zone login flow to the Keycloak browser flow without OTP. Usage: zone-login-no-mfa.sh <zone>
# The openDesk bootstrap keeps its 2fa-browser flow after the 2FA groups are removed, so this script sets the flow.
set -euo pipefail
# A relative KUBECONFIG path starts at the current folder, so it becomes absolute before the cd.
if [ -n "${KUBECONFIG:-}" ]; then KUBECONFIG=$(realpath "$KUBECONFIG"); fi
cd "$(dirname "$0")"
zone=$1
export KUBECONFIG=${KUBECONFIG:-$(realpath ../private/kubeconfig)}
password=$(kubectl -n "$zone" get secret keycloak-admin-password -o jsonpath='{.data.adminPassword}' | base64 -d)
kubectl -n "$zone" exec -i ums-keycloak-0 -c main -- env KC_PASSWORD="$password" bash -s <<'EOF'
set -euo pipefail
kcadm() { /opt/keycloak/bin/kcadm.sh "$@" --config /tmp/kcadm.config; }
kcadm config credentials --server http://localhost:8080 --realm master --user kcadmin --password "$KC_PASSWORD" >/dev/null
# A zone installed with two-factor login off has no 2fa-browser flow and no "2FA role". The openDesk Keycloak bootstrap
# reads both, so a copy of the browser flow and an unassigned role stand in for them.
kcadm get authentication/flows -r opendesk --fields alias | grep -q '"2fa-browser"' || kcadm create authentication/flows/browser/copy -r opendesk -s newName=2fa-browser
kcadm get roles -r opendesk --fields name | grep -q '"2FA role"' || kcadm create roles -r opendesk -s 'name=2FA role'
# The same bootstrap also leaves out the LDAP group mapper. Without it no user has a group, and Keycloak leaves out the
# application scopes that depend on group roles, so Nextcloud, Element and XWiki get no user claims.
provider=$(kcadm get components -r opendesk -q type=org.keycloak.storage.UserStorageProvider --fields id | grep '"id"' | head -1 | cut -d'"' -f4)
if ! kcadm get components -r opendesk -q parent="$provider" --fields name | grep -q '"univention-groups"'; then
  kcadm create components -r opendesk -s name=univention-groups -s providerId=group-ldap-mapper \
    -s providerType=org.keycloak.storage.ldap.mappers.LDAPStorageMapper -s parentId="$provider" \
    -s 'config."groups.dn"=["cn=groups,dc=swp-ldap,dc=internal"]' -s 'config."group.name.ldap.attribute"=["cn"]' \
    -s 'config."group.object.classes"=["univentionGroup"]' -s 'config."preserve.group.inheritance"=["false"]' \
    -s 'config."ignore.missing.groups"=["false"]' -s 'config."membership.ldap.attribute"=["memberUid"]' \
    -s 'config."membership.attribute.type"=["UID"]' -s 'config."membership.user.ldap.attribute"=["uid"]' \
    -s 'config."memberof.ldap.attribute"=["memberOf"]' -s 'config."mode"=["READ_ONLY"]' \
    -s 'config."user.roles.retrieve.strategy"=["LOAD_GROUPS_BY_MEMBER_ATTRIBUTE"]' -s 'config."groups.path"=["/"]' \
    -s 'config."drop.non.existing.groups.during.sync"=["false"]'
  mapper=$(kcadm get components -r opendesk -q parent="$provider" -q name=univention-groups --fields id | grep '"id"' | cut -d'"' -f4)
  kcadm create "user-storage/$provider/mappers/$mapper/sync?direction=fedToKeycloak" -r opendesk >/dev/null
fi
kcadm update realms/opendesk -s browserFlow=browser
kcadm get realms/opendesk --fields browserFlow
rm -f /tmp/kcadm.config
EOF
