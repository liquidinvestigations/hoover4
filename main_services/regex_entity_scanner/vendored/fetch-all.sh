#!/usr/bin/env bash
#
# Fetches every vendored corpus. Runs inside the dev container:  ./shell.sh vendored/fetch-all.sh
#
# GLEIF is excluded: it is a multi-gigabyte download that nothing needs until LEI resolution does.
# Run `vendored/fetch/gleif.sh` for that.
#
# Named arguments run only those fetchers:  vendored/fetch-all.sh cldr iana-tlds

source "$(dirname -- "${BASH_SOURCE[0]}")/fetch/common.sh"

if [[ $# -gt 0 ]]; then
    scripts=()
    for name in "$@"; do
        scripts+=("${VENDOR_ROOT}/fetch/${name%.sh}.sh")
    done
else
    scripts=()
    for script in "${VENDOR_ROOT}"/fetch/*.sh; do
        case "$(basename "$script")" in
            common.sh|gleif.sh) continue ;;
        esac
        scripts+=("$script")
    done
fi

failed=()
for script in "${scripts[@]}"; do
    name="$(basename "$script" .sh)"
    printf '\n== %s\n' "$name"
    if ! bash "$script"; then
        failed+=("$name")
        printf '  FAILED\n'
    fi
done

printf '\nvendored tree: %s\n' "$(du -sh "$VENDOR_ROOT" | cut -f1)"
if [[ ${#failed[@]} -gt 0 ]]; then
    printf 'failed: %s\n' "${failed[*]}"
    exit 1
fi
