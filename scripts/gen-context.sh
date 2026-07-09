#!/bin/sh
# Regenerates both SigMap context tiers.
#
# sigmap's own CLI treats "root per-module pass" and "--monorepo per-package
# pass" as mutually exclusive within a single invocation (config.monorepo=true
# makes a bare `sigmap` skip the root pass entirely and vice versa), so we run
# both explicitly to get the full tree:
#   - global tier:  .github/context-<module>.md + root CLAUDE.md/AGENTS.md
#   - package tier: <package>/.github/context-*.md + <package>/CLAUDE.md/AGENTS.md
set -e
cd "$(dirname "$0")/.."
sigmap
sigmap --monorepo
