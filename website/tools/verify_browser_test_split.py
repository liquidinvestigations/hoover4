#!/usr/bin/env python3
"""Compare concatenated screenshot scenarios with the per-slug directory.

The comparison is the parsed scenario list the capture engine uses: count, names,
block-relative order, url, actions, and every other key except ``summary`` and ``slug``.

    python3 website/tools/verify_browser_test_split.py \\
        --baseline /tmp/screenshots-baseline.ini \\
        --directory website/browser-tests

Pass ``--probe-failure`` to alter one url in memory and confirm this script reports a diff.
A verifier that cannot fail is worse than none.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def load_capture_module():
    path = Path(__file__).with_name("capture_screenshots.py")
    spec = importlib.util.spec_from_file_location("capture_screenshots", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_splitter_module():
    path = Path(__file__).with_name("split_browser_tests.py")
    spec = importlib.util.spec_from_file_location("split_browser_tests", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def page_payload(page) -> dict[str, object]:
    return {
        "url": page.url,
        "actions": list(page.actions),
        "full_page": page.full_page,
        "settle_ms": page.settle_ms,
        "allow_error_markers": page.allow_error_markers,
        "allow_http_errors": page.allow_http_errors,
        "allow_console": list(page.allow_console),
        "expect": list(page.expect),
        "scroll_captures": list(page.scroll_captures),
        "requires_dataset": list(page.requires_dataset),
        "viewport": page.viewport,
        "manual_asset": page.manual_asset,
        "color_scheme": page.color_scheme,
        "procedure": page.procedure,
        "init_script": page.init_script,
        "document_fixture": page.document_fixture,
    }


def diffs(baseline_pages, split_pages, expected_order: list[str]) -> list[str]:
    found: list[str] = []
    base_names = [page.name for page in baseline_pages]
    split_names = [page.name for page in split_pages]
    if len(baseline_pages) != len(split_pages):
        found.append(
            f"count: baseline {len(baseline_pages)} split {len(split_pages)}"
        )
    if set(base_names) != set(split_names):
        missing = sorted(set(base_names) - set(split_names))
        extra = sorted(set(split_names) - set(base_names))
        found.append(f"names: missing {missing} extra {extra}")
    if split_names != expected_order:
        found.append("order: split slug-number order does not match the numbering rule")
        found.append(f"  expected {expected_order}")
        found.append(f"  split    {split_names}")
    base_by_name = {page.name: page for page in baseline_pages}
    split_by_name = {page.name: page for page in split_pages}
    for name in base_names:
        if name not in split_by_name:
            continue
        left = page_payload(base_by_name[name])
        right = page_payload(split_by_name[name])
        for key in left:
            if left[key] != right[key]:
                found.append(f"{name}.{key}: baseline {left[key]!r} split {right[key]!r}")
    return found


def expected_name_order(baseline_pages, splitter) -> list[str]:
    names = [page.name for page in baseline_pages]
    return [name for name, _base, _slug in splitter.number_sections(names)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument(
        "--probe-failure",
        action="store_true",
        help="alter one url in memory and require a diff",
    )
    args = parser.parse_args()
    capture = load_capture_module()
    splitter = load_splitter_module()
    baseline_pages = capture.parse_pages(args.baseline)
    split_pages = capture.load_scenario_pages(args.directory)
    order = expected_name_order(baseline_pages, splitter)
    found = diffs(baseline_pages, split_pages, order)
    print(f"baseline count: {len(baseline_pages)}")
    print(f"split count:    {len(split_pages)}")
    print(f"names match:    {set(p.name for p in baseline_pages) == set(p.name for p in split_pages)}")
    print(f"order match:    {[p.name for p in split_pages] == order}")
    if args.probe_failure:
        if found:
            print("probe skipped: the split already differs")
            for line in found:
                print(line)
            return 1
        original_url = split_pages[0].url
        split_pages[0].url = "/probe-failure-does-not-exist"
        probed = diffs(baseline_pages, split_pages, order)
        if not probed:
            print("probe failed: a changed url produced no diff")
            return 1
        print("probe produced a diff, as required:")
        for line in probed:
            print(line)
        split_pages[0].url = original_url
        found = diffs(baseline_pages, split_pages, order)
        if found:
            print("split differs after restoring the probe")
            for line in found:
                print(line)
            return 1
        print("faithful split: count, names, numbering-rule order, and keys match")
        return 0
    if found:
        print("DIFF")
        for line in found:
            print(line)
        return 1
    print("OK: count, names, order, url, actions, and other keys match")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
