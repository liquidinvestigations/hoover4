#!/usr/bin/env python3
"""Extract Mermaid blocks and render them with a versioned CLI image."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid

# The extractor runs inside the documentation image. The host starts renderer containers.
IMAGE = "ghcr.io/mermaid-js/mermaid-cli/mermaid-cli:11.12.0"


def extract(root, output):
    from markdown import parse
    names = Path("/tmp/docs-index").read_text().split("\0")
    ownership = json.loads((root / "scripts/docs/ownership.json").read_text())
    output.mkdir(parents=True, exist_ok=True)
    blocks = []
    for name in sorted(names):
        if not name.lower().endswith(".md") or name in ownership:
            continue
        for line, code in parse((root / name).read_text())["diagrams"]:
            filename = f"diagram-{len(blocks) + 1:04}.mmd"
            (output / filename).write_text(code)
            blocks.append(dict(source=name, line=line, file=filename))
    (output / "manifest.json").write_text(json.dumps(blocks, indent=2) + "\n")


def render(output):
    failed = False
    for row in json.loads((output / "manifest.json").read_text()):
        svg = row["file"] + ".svg"
        name = "hoover4-docs-" + uuid.uuid4().hex
        command = ["docker", "run", "--rm", "--name", name, "--network", "none", "--user", "0",
                   "-v", f"{output.resolve()}:/data:rw", IMAGE,
                   "-i", f"/data/{row['file']}", "-o", f"/data/{svg}", "-b", "white"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=90)
            log = result.stdout + result.stderr
            ok = result.returncode == 0 and (output / svg).is_file()
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=15)
            log, ok = "The renderer exceeded 90 seconds.\n", False
        (output / (row["file"] + ".log")).write_text(log)
        failed |= not ok
        print(f"{row['source']}:{row['line']}: {'rendered' if ok else 'failed'} ({row['file']})")
    return int(failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("extract", "render"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.operation == "extract":
        extract(Path("/repo"), args.output)
    else:
        sys.exit(render(args.output))
