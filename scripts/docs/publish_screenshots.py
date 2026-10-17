#!/usr/bin/env python3
"""Copy reviewed captures and write public provenance without private run metadata."""
import argparse
import configparser
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

from check import ROOT, png_size


def inside(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("The selected path leaves its containing directory.")
    return path


def prepare(root, run, mapping):
    manifest = json.loads((run / "manifest.json").read_text())
    revision = manifest.get("revision", "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("The capture manifest needs a full source revision.")
    if any(manifest.get("totals", {}).get(key, 0) for key in ("application_error", "incomplete_execution")):
        raise ValueError("Resolve failed or incomplete capture runs before publication.")
    captures = {c["file"]: (page, c) for page in manifest.get("pages", []) for c in page.get("captures", [])}
    results, destinations = [], set()
    for entry in mapping:
        source = entry["capture"]
        image = entry["image"]
        scenario = entry["scenario"]
        page, capture = captures[source]
        if page.get("skipped") or page.get("verdict") in ("application_error", "incomplete_execution"):
            raise ValueError("The selected scenario did not complete.")
        if capture.get("actual_png") != [1400, 900] or capture.get("requested") != [1400, 900]:
            raise ValueError("The selected capture must measure 1400 by 900 pixels.")
        if ".FAILED." in source or ".full_page." in source:
            raise ValueError("Select a viewport capture from a completed scenario.")
        src = inside(run, source)
        dst = inside(root, image)
        case = inside(root, scenario)
        if not image.startswith("docs/") or dst.suffix.lower() != ".png" or image in destinations:
            raise ValueError("Each destination must be a distinct documentation PNG path.")
        if not scenario.startswith("website/browser-tests/") or not case.is_file():
            raise ValueError("Select an existing browser scenario file.")
        definition = configparser.ConfigParser(interpolation=None)
        definition.read(case)
        if page.get("slug") not in {case.stem, *definition.sections()}:
            raise ValueError("The selected scenario does not match the captured page.")
        if png_size(src) != (1400, 900):
            raise ValueError("The PNG dimensions differ from the capture record.")
        destinations.add(image)
        record = dict(image=image, scenario=scenario, revision=revision,
                      captured_at=datetime.fromtimestamp(src.stat().st_mtime, timezone.utc).isoformat(),
                      sha256=hashlib.sha256(src.read_bytes()).hexdigest())
        results.append((src, dst, record))
    if not results:
        raise ValueError("Select at least one reviewed capture.")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rows = prepare(ROOT, args.run, json.loads(args.mapping.read_text()))
    if not args.write:
        print(json.dumps([r for _, _, r in rows], indent=2))
        return
    filename = ROOT / "docs/screenshot-provenance.json"
    old = json.loads(filename.read_text()).get("screenshots", []) if filename.exists() else []
    merged = {entry["image"]: entry for entry in old}
    for source, destination, record in rows:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        merged[record["image"]] = record
    filename.write_text(json.dumps({"screenshots": sorted(merged.values(), key=lambda r: r["image"])}, indent=2) + "\n")
    print(f"Published {len(rows)} screenshots and their provenance.")


if __name__ == "__main__":
    main()
