#!/usr/bin/env bash
#
# Interactive shell in a throwaway dev container on the working tree. Any arguments are run as a
# command instead of starting a shell:  ./shell.sh cargo test

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

ensure_dev_image

if [[ $# -eq 0 ]]; then
    set -- bash
fi

# A terminal is allocated only when there is one on both ends. Docker's `--tty` joins the
# container's stdout and stderr into a single stream, so allocating one unconditionally puts a
# script's progress line into the file its output was redirected to —
# `./shell.sh python3 extract.py > cases.jsonl` would write a corpus with a count in the middle of
# it. Redirected output keeps the two streams apart.
tty_args=()
if [[ -t 0 && -t 1 ]]; then
    tty_args=(--interactive --tty)
fi

exec docker run --rm "${tty_args[@]}" \
    "${DEV_RUN_ARGS[@]}" \
    "$DEV_IMAGE" \
    "$@"
