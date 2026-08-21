# Shared helpers for the fetch scripts. Sourced, never executed.
#
# Every fetch stages its download or clone under `tmp/` and copies only the subset we actually use
# into `vendored/`. Keeping the staging area separate is what allows a re-fetch to be reviewed as a
# diff of the vendored subset rather than of an entire upstream tree.

set -euo pipefail

VENDOR_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd -- "${VENDOR_ROOT}/.." && pwd)"
STAGE="${REPO_ROOT}/tmp/stage"
DATA="${VENDOR_ROOT}/data"
REFERENCE="${VENDOR_ROOT}/reference"
LICENSES="${VENDOR_ROOT}/licenses"

mkdir -p "$STAGE" "$DATA" "$REFERENCE" "$LICENSES"

# Progress goes to stderr: several helpers echo a path on stdout for the caller to capture, and a
# progress line landing in that capture turns into a path that does not exist.
note() {
    printf '  %s\n' "$*" >&2
}

# Shallow clone into the staging area, or update the clone that is already there.
clone() {
    local url="$1" dir="${STAGE}/$2"
    if [[ -d "${dir}/.git" ]]; then
        note "updating $2"
        git -C "$dir" fetch --depth 1 origin HEAD >/dev/null 2>&1
        git -C "$dir" reset --hard FETCH_HEAD >/dev/null 2>&1
    else
        note "cloning $2"
        git clone --depth 1 --quiet "$url" "$dir"
    fi
    printf '%s' "$dir"
}

download() {
    local url="$1" dest="$2"
    note "downloading $(basename "$dest")"
    curl --fail --silent --show-error --location --output "$dest" "$url"
}

# Extracts the newest tarball of an npm package into the staging area and echoes its path.
npm_tarball() {
    local package="$1"
    local meta="${STAGE}/${package}.json"
    curl --fail --silent --show-error --location \
        --header 'Accept: application/vnd.npm.install-v1+json' \
        --output "$meta" "https://registry.npmjs.org/${package}"
    local version url dir
    version="$(jq -r '.["dist-tags"].latest' "$meta")"
    url="$(jq -r --arg v "$version" '.versions[$v].dist.tarball' "$meta")"
    dir="${STAGE}/${package}-${version}"
    if [[ ! -d "$dir" ]]; then
        note "downloading ${package}@${version}"
        curl --fail --silent --show-error --location --output "${STAGE}/${package}.tgz" "$url"
        mkdir -p "$dir"
        tar -xzf "${STAGE}/${package}.tgz" -C "$dir" --strip-components=1
    fi
    printf '%s' "$dir"
}

# Replaces a vendored subtree wholesale, so files deleted upstream disappear here too.
replace_dir() {
    rm -rf "$1"
    mkdir -p "$1"
}

# Records the upstream commit or version alongside the data, because a vendored snapshot without a
# provenance stamp cannot be diffed against its upstream later.
stamp() {
    local target="$1" source_desc="$2" revision="$3"
    printf '%s\n%s\n' "$source_desc" "$revision" > "${target}/.upstream"
}

git_head() {
    git -C "$1" rev-parse HEAD
}

# The upstream's HEAD commit, for a fetch that downloads individual files instead of cloning. A
# stamp naming a commit is what makes the vendored subset diffable against its upstream later, and
# a handful of raw files is not worth a clone of the tree they sit in.
remote_head() {
    git ls-remote "$1" HEAD | cut -f1
}
