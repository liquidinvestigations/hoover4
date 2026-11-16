# Source this file in a platform install script. It defines helm_release.
#
# helm_release <helm> <release> <namespace> <repo/chart> <version> <values file> [helm upgrade options...]
# Install or upgrade a release only when its chart version, its status or its values differ. A Helm upgrade without a
# change still writes a new release revision, and it gives back the chart values of the fields that cpu_policy.py
# patches afterwards, so each unneeded upgrade would restart the pods twice. The values file holds every value of the
# release: the options are only flags such as --wait, --timeout or --force-conflicts.
helm_release() {
  local helm=$1 release=$2 namespace=$3 chart=$4 version=$5 values=$6
  shift 6
  if "$helm" get values "$release" -n "$namespace" -o json 2>/dev/null | python3 -c '
import json, sys, yaml
current, wanted = json.load(sys.stdin), yaml.safe_load(open(sys.argv[1])) or {}
sys.exit(0 if current == wanted else 1)' "$values" &&
    [ "$("$helm" list -n "$namespace" --filter "^$release\$" --deployed -o json | python3 -c '
import json, sys
rows = json.load(sys.stdin)
print(rows[0]["chart"] if rows else "")')" = "${chart#*/}-$version" ]; then
    echo "$release ${chart#*/}-$version is deployed with the values of $values"
    return
  fi
  "$helm" upgrade --install "$release" "$chart" --version "$version" --namespace "$namespace" --create-namespace \
    -f "$values" "$@"
}
