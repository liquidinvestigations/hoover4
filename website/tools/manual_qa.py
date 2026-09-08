#!/usr/bin/env python3
"""Validate and select the browser scenarios for the manual QA matrix."""

from __future__ import annotations

import argparse
import configparser
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class Case:
    row: int
    title: str
    fixtures: tuple[str, ...]
    scenarios: tuple[str, ...]
    variations: tuple[str, ...]


CASES = (
    Case(6, "Search for CSQU3054383", ("shipping_manifest",), ("view-doc-entity-card",), ("keyboard-find", "popup-return", "no-match")),
    Case(7, "Search for hoover", ("enron_like_text_substitute",), ("view-doc-text",), ("stable-identity", "page-return")),
    Case(8, "Search collection filtered", ("easychair_odt",), ("search-with-chips", "filter-pane-filesize"), ("find-zero-clear", "reload-persistence")),
    Case(9, "Search collection filtered file type", ("security_incident",), ("filter-pane-filetypes", "search-filetype-chip"), ("incremental-types", "popover-appearance")),
    Case(10, "Search collection filtered file location", ("invoice_and_generator",), ("storage-in-folder-search", "search-filelocation-dataset-applied"), ("handoff", "return-and-clear")),
    Case(11, "Search collection filter date", ("easychair_odt",), ("filter-pane-date", "filter-pane-date-before", "filter-pane-date-after"), ("boundary-input", "reversed-dates")),
    Case(12, "Search collection filter email", ("romanian_email",), ("storage-email-preview", "view-doc-email-metadata", "view-doc-three-tabs"), ("attachment-tabs", "combined-sender")),
    Case(13, "Search collection filter entity", ("easychair_odt",), ("filter-pane-entities",), ("exact-entity", "entity-no-match", "popover-appearance")),
    Case(14, "Sort on dates", (), ("qa-sort-date-directions",), ("both-directions", "reload-state")),
    Case(15, "Sort on size", (), ("qa-sort-file-size-directions",), ("cross-page-order", "metadata-agreement")),
    Case(16, "Sort on name", (), ("qa-sort-name-directions",), ("name-comparator", "state-persistence")),
    Case(17, "Sort on relevance", ("parent_archive",), ("qa-sort-explicit-relevance", "qa-sort-empty-default", "qa-sort-legacy-ascending-relevance"), ("explicit-relevance", "empty-query")),
    Case(18, "Open and test PDF functionality", ("stanley_pdf_with_ocr", "born_digital_pdf_without_ocr"), ("qa-pdf-full-source-switch", "qa-pdf-full-delayed-source-switch", "qa-pdf-preview-source-switch"), ("active-find-source-switch", "page-and-zoom", "no-match", "source-appearance")),
    Case(19, "Open and test Email viewer", ("romanian_email",), ("view-doc-email-metadata", "view-doc-three-tabs"), ("preview-parity", "attachment-return")),
    Case(20, "Zip test preview and viewer", ("parent_archive",), ("view-doc-file-locations-source",), ("no-source-archive", "separate-container-action")),
    Case(21, "Zip test file storage", ("directory_archive",), ("storage-container-by-url", "qa-storage-archive-highlight", "qa-storage-back"), ("search-handoff", "return-navigation", "archive-highlight")),
    Case(22, "Table test preview and viewer", ("manual_table_substitute", "screenshot_table_corpus", "screenshot_wide_table"), ("qa-table-data-sort-filter", "qa-table-modal-geometry", "qa-table-modal-backdrop", "qa-table-modal-keyboard", "qa-table-modal-light-colors", "qa-table-modal-dark-colors", "qa-table-picker-visibility"), ("sort-and-filter", "columns-and-reload", "modal-geometry", "light-and-dark")),
    Case(23, "Entities viewer", ("easychair_office",), ("view-doc-entity-card", "view-doc-entity-card-stale"), ("multiple-values", "stale-entity", "appearance")),
    Case(24, "File tree explorer", ("leaf_dataset", "deep_tree", "directory_archive"), ("storage-tree-unified", "storage-shapes-deepest", "qa-storage-leaf-dataset", "qa-storage-warm-navigation"), ("keyboard-tree", "leaf-disclosure", "cache-and-history")),
    Case(25, "Run LLM query", (), ("ai-chat", "ai-chat-history"), ("submit-and-complete", "keyboard-and-history")),
)


EXECUTABLE_NAMES = (
    "manual-shipping", "manual-mail-search", "manual-size-filters", "manual-type-filters",
    "manual-folder-search", "manual-dates", "manual-email-filters", "manual-entity-filter",
    "manual-sort-dates", "manual-sort-size", "manual-sort-name", "manual-relevance",
    "manual-pdf", "manual-email-viewer", "manual-archive-viewer", "manual-archive-storage",
    "manual-table", "manual-entities", "manual-tree",
)
CASES = tuple(replace(case, scenarios=(EXECUTABLE_NAMES[case.row - 6],)) if case.row != 25 else case for case in CASES)
CASES = tuple(replace(case, variations=("sort-and-filter", "columns-and-reload", "no-matches", "keyboard", "single-modal-and-palette")) if case.row == 22 else
              replace(case, variations=("two-datasets", "keyboard-tree", "reload-and-narrow-view", "leaf-disclosure", "cache-and-history")) if case.row == 24 else
              replace(case, variations=("minimum-turn", "composer-keyboard")) if case.row == 25 else case for case in CASES)


def select_cases(selection: str) -> list[Case]:
    if not selection:
        return list(CASES)
    wanted = {int(value.strip()) for value in selection.split(",") if value.strip()}
    selected = [case for case in CASES if case.row in wanted]
    missing = wanted - {case.row for case in selected}
    if missing:
        raise ValueError(f"unknown manual QA rows: {sorted(missing)}")
    if not selected:
        raise ValueError("manual QA selection is empty")
    return selected


def scenario_names(ini_path: Path) -> set[str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ini_path, encoding="utf-8")
    return set(parser.sections())


def prerequisite_status(cases: list[Case], profile: dict[str, object]) -> list[dict[str, object]]:
    outcomes = {item["fixture"]: item["status"] for item in profile.get("outcomes", [])}
    results = []
    for case in cases:
        missing = [fixture for fixture in case.fixtures if outcomes.get(fixture) != "verified"]
        results.append({"row": case.row, "status": "ready" if not missing else "unmet_prerequisite", "missing": missing})
    return results


def plan(cases: list[Case], profile: dict[str, object], ini_path: Path) -> dict[str, object]:
    names = scenario_names(ini_path)
    missing_scenarios = sorted({scenario for case in cases for scenario in case.scenarios if scenario not in names})
    prerequisites = prerequisite_status(cases, profile)
    return {
        "cases": [asdict(case) for case in cases],
        "procedures": [f"row-{case.row:02d}-baseline" for case in cases] + [f"row-{case.row:02d}-{variation}" for case in cases for variation in case.variations],
        "capture_scenarios": [scenario for case in cases for scenario in case.scenarios if case.row != 25 and next(item for item in prerequisites if item["row"] == case.row)["status"] == "ready" and scenario in names],
        "chat_required": any(case.row == 25 for case in cases),
        "prerequisites": prerequisites,
        "missing_scenarios": missing_scenarios,
        "result": "ready" if not missing_scenarios and all(item["status"] == "ready" for item in prerequisites) else "incomplete_execution",
    }


def summarize(root: Path, resolutions: list[str], browser_exit: int, chat_exit: int, preflight_exit: int) -> int:
    plan_data = json.loads((root / "manual-qa-plan.json").read_text())
    records = []
    for case in plan_data["cases"]:
        for resolution in resolutions:
            if case["row"] == 25:
                manifest = root / "chat/latest/chat/chat_manifest.json"
                conversations = json.loads(manifest.read_text()) if manifest.is_file() else []
                complete = False
                for item in conversations:
                    history = item.get("history", {}).get("by_resolution", {}).get(resolution, {})
                    switch = history.get("switch", {})
                    complete |= bool(item.get("submission_ok") and item.get("turn_started") and item.get("completed_answer_present")
                                     and item.get("captures", {}).get(resolution) and history.get("reload_survived") is True
                                     and switch.get("attempted") is True and switch.get("survived") is True)
                status = "passed" if chat_exit == 0 and complete else "application_error" if chat_exit == 1 else "incomplete_execution"
                for variation in ["baseline", *case["variations"]]:
                    records.append({"row": 25, "procedure": variation, "resolution": resolution, "status": status,
                                    "evidence": "chat/latest/chat/chat_manifest.json", "chat_exit": chat_exit})
                continue
            files = list((root / "browser/latest" / resolution).glob(f"*{case['scenarios'][0]}.procedures.json"))
            observed = {item["procedure"]: item for item in json.loads(files[0].read_text())} if len(files) == 1 else {}
            for variation in ["baseline", *case["variations"]]:
                item = observed.get(variation)
                records.append({"row": case["row"], "procedure": variation, "resolution": resolution,
                                "status": item["status"] if item and item["status"] != "running" else "incomplete_execution",
                                "error": item.get("error") if item else "No completed procedure evidence exists.",
                                "evidence": str(files[0].relative_to(root)) if files else None})
    failed = any(item["status"] == "application_error" for item in records) or browser_exit == 1 or chat_exit == 1
    incomplete = any(item["status"] != "passed" for item in records) or preflight_exit != 0
    exit_status = 1 if failed else 2 if incomplete else 0
    (root / "manual-qa-results.json").write_text(json.dumps({"exit_status": exit_status, "procedures": records}, indent=2) + "\n")
    return exit_status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=Path("website/test_reports/manual_qa_fixtures.json"))
    parser.add_argument("--ini", type=Path, default=Path("website/screenshots.ini"))
    parser.add_argument("--select", default="")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--print-scenarios", action="store_true")
    parser.add_argument("--summarize", type=Path)
    parser.add_argument("--resolutions", default="720p,1080p")
    parser.add_argument("--browser-exit", type=int, default=2)
    parser.add_argument("--chat-exit", type=int, default=2)
    parser.add_argument("--preflight-exit", type=int, default=0)
    args = parser.parse_args()
    if args.summarize:
        return summarize(args.summarize, args.resolutions.split(","), args.browser_exit, args.chat_exit, args.preflight_exit)
    try:
        selected = select_cases(args.select)
        result = plan(selected, json.loads(args.profile.read_text(encoding="utf-8")), args.ini)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.print_scenarios:
        print(",".join(result["capture_scenarios"]))
    return 0 if result["result"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
