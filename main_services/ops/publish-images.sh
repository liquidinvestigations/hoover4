#!/usr/bin/env bash
# Builds every hoover4 image with its code baked in, and pushes it to the local Nomad
# cluster's own registry. Run by hand. No continuous integration calls this script.
#
# Usage: main_services/ops/publish-images.sh <version>
#
# The version becomes the tag on every image, the same tag across the whole set. There
# is no default; a missing version stops the script before it builds anything. The
# registry's address is read from hoover4.ini ([cluster] registry_address) and never
# appears in this script or in any other tracked file.
#
# Two services, hoover4-worker and hoover4-ops, publish from one build
# (main_services/processing/Dockerfile), because the compose stack already runs both
# from the same image with a different command. Two more, hoover4-internal-search-agent
# and hoover4-full-research-agent, share a build the same way. Both pairs still get one
# registry repository each, by decision, so the same image is tagged and pushed twice.
set -euo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
  echo "usage: $0 <version>" >&2
  echo "example: $0 0.1.0" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INI_PATH="$REPO_ROOT/hoover4.ini"

REGISTRY="$(python3 - "$INI_PATH" <<'PYEOF'
import configparser
import sys

parser = configparser.ConfigParser(inline_comment_prefixes=(";",))
parser.read(sys.argv[1])
print(parser.get("cluster", "registry_address", fallback="").strip())
PYEOF
)"

if [ -z "$REGISTRY" ]; then
  echo "no [cluster] registry_address set in $INI_PATH; nothing to push to" >&2
  exit 1
fi

echo "registry: $REGISTRY"
echo "version: $VERSION"
echo "a tag that already exists at this version and this registry is overwritten by this run."

SUMMARY_FILE="$(mktemp)"
trap 'rm -f "$SUMMARY_FILE"' EXIT

# Builds one image and pushes one tag. Records one summary line.
push_tag() {
  local name="$1" context="$2" dockerfile="$3"
  local ref="$REGISTRY/$name:$VERSION"
  echo ""
  echo "=== $name: building from $context/$dockerfile ==="
  local start end duration
  start=$(date +%s)
  docker build -f "$context/$dockerfile" -t "$ref" "$context"
  end=$(date +%s)
  duration=$((end - start))
  echo "=== $name: pushing $ref ==="
  local digest_file digest size
  digest_file="$(mktemp)"
  docker push --digestfile "$digest_file" "$ref"
  digest="$(cat "$digest_file")"
  rm -f "$digest_file"
  size="$(docker image inspect "$ref" --format '{{.Size}}')"
  printf '%s|%s|%s|%s|%ss\n' "$name" "$ref" "$digest" "$size" "$duration" >> "$SUMMARY_FILE"
}

# Tags and pushes an already-built image under a second service name, with no rebuild.
retag_and_push() {
  local built_name="$1" new_name="$2"
  local built_ref="$REGISTRY/$built_name:$VERSION"
  local new_ref="$REGISTRY/$new_name:$VERSION"
  echo ""
  echo "=== $new_name: retagging $built_ref, no rebuild ==="
  docker tag "$built_ref" "$new_ref"
  local digest_file digest size
  digest_file="$(mktemp)"
  docker push --digestfile "$digest_file" "$new_ref"
  digest="$(cat "$digest_file")"
  rm -f "$digest_file"
  size="$(docker image inspect "$new_ref" --format '{{.Size}}')"
  printf '%s|%s|%s|%s|shared build\n' "$new_name" "$new_ref" "$digest" "$size" >> "$SUMMARY_FILE"
}

# main compose file
push_tag "garage-init" "$REPO_ROOT/main_services/ops/docker/garage" "Dockerfile"
push_tag "hoover4-processing-pdf-to-html" "$REPO_ROOT/main_services/ops/docker/pdf-to-html" "Dockerfile"
push_tag "hoover4-website" "$REPO_ROOT/website" "Dockerfile.release"
push_tag "hoover4-worker" "$REPO_ROOT/main_services/processing" "Dockerfile"
retag_and_push "hoover4-worker" "hoover4-ops"

# model twins
push_tag "hoover4-tesseract-cpu" "$REPO_ROOT/main_services/ocr_tesseract" "Dockerfile"
push_tag "hoover4-ocr-pdf" "$REPO_ROOT/main_services/ocr_pdf" "Dockerfile"
push_tag "hoover4-ner-spacy" "$REPO_ROOT/main_services/ner_spacy" "Dockerfile"
push_tag "hoover4-regex-entity-scanner" "$REPO_ROOT/main_services/regex_entity_scanner" "Dockerfile.release"

# agent and MCP servers
push_tag "hoover4-mcp-collections" "$REPO_ROOT/main_services/agents" "collection_search_server/Dockerfile"
push_tag "hoover4-mcp-whois" "$REPO_ROOT/main_services/agents" "whois_search_server/Dockerfile"
push_tag "hoover4-mcp-todo" "$REPO_ROOT/main_services" "agents/agent_todo_server/Dockerfile"
push_tag "hoover4-mcp-metasearch" "$REPO_ROOT/main_services/agents" "metasearch_server/Dockerfile"
push_tag "hoover4-mcp-browser" "$REPO_ROOT/main_services/agents" "browser_use_server/Dockerfile"
push_tag "hoover4-internal-search-agent" "$REPO_ROOT/main_services/agents/research_agent" "Dockerfile"
retag_and_push "hoover4-internal-search-agent" "hoover4-full-research-agent"

# GPU tier
push_tag "hoover4-ai-server" "$REPO_ROOT/ai_services" "hoover4_ai_server/Dockerfile"
push_tag "hoover4-easyocr-gpu" "$REPO_ROOT/ai_services/easyocr_server" "Dockerfile"

echo ""
echo "=== summary: service | tag | digest | size (bytes) | build duration ==="
column -t -s'|' "$SUMMARY_FILE"
