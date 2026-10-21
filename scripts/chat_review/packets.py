"""Assemble source records without database or model calls."""

from collections import defaultdict
from copy import deepcopy
from types import SimpleNamespace
from .schema import (Incomplete, digest, packet_digest, require, text_digest,
                     validate_packet)
from tasks.P_workspace.selection import delivered_reports


def assemble_packet(run, messages, file_versions, source_items, identity):
    """Select immutable versions from one answer thread."""
    require(run["owner"] == identity["owner"] and run["session_id"] == identity["session_id"], "Run owner or session differs.")
    answer_thread = run["thread_id"]
    final = [SimpleNamespace(**m, usage=m["metadata"].get("usage", {}),
                             tool_name=m["metadata"].get("tool_name", ""),
                             tool_call_id=m["metadata"].get("tool_call_id", ""))
             for m in messages if m["thread_id"] == answer_thread and m["is_final"]]
    selected = delivered_reports(final)
    if selected != run["published_reports"]:
        raise Incomplete("Published reports differ from successful mutation receipts.")
    files = []
    for item in selected:
        key = (item["name"], item["version"])
        v = file_versions.get(key)
        if v is None:
            raise Incomplete("A delivered file version is unavailable.")
        require((v["username"], v["session_id"], v["name"], v["version"]) ==
                (identity["owner"], identity["session_id"], *key), "File owner, session, or version differs.")
        files.append({"name": item["name"], "version": item["version"],
                      "content": v["content"], "digest": text_digest(v["content"])})
    closing = run["closing_answer"]
    delivery = {"files": files, "closing_answer": {"message_idx": run["answer_seq"],
                "content": closing, "digest": text_digest(closing)}}
    omissions = list(run.get("history_omissions", []))
    if any(not m["is_final"] for m in messages):
        omissions.append("Partial stored messages are excluded from visible history requests.")
    packet = {"schema_version": 1, "identity": deepcopy(identity),
              "request": {"current": run["request"], "task_state": run.get("task_state", {}),
                          "amendments": run.get("amendments", []), "prior_requests": run.get("prior_requests", [])},
              "delivery": delivery, "citations": run.get("citations", []),
              "evidence": sorted(deepcopy(source_items), key=lambda e: e["id"]),
              "history": {"messages": deepcopy(messages), "complete": not omissions, "omissions": omissions},
              "coverage": {"requested": run.get("requirements", []),
                           "available": [f["name"] for f in files] + ["<closing>"],
                           "missing": run.get("missing", [])}}
    packet["identity"]["packet_digest"] = packet_digest(packet)
    return validate_packet(packet)


def computed_table_facts(cells, reading, population):
    """Compute groups only from an explicitly complete, identified row population."""
    require(isinstance(cells, list) and all(isinstance(r, dict) for r in cells), "Table cells must be row objects.")
    require(isinstance(reading, dict) and set(reading) == {"id_column", "group_column", "interpretation"}, "Specify the table reading.")
    require(isinstance(population, dict) and set(population) == {"complete", "row_count", "source_digest", "extent", "filters"}, "Specify the table population.")
    manifest = {"input_digest": digest(cells), "reading": reading, "population": population}
    if population["complete"] is not True or population["row_count"] != len(cells):
        return {**manifest, "state": "incomplete", "operations": []}
    groups, empty, mapping = defaultdict(list), [], {}
    for row in cells:
        require(reading["id_column"] in row and reading["group_column"] in row, "A selected column is absent.")
        key, group = row[reading["id_column"]], row[reading["group_column"]]
        require(isinstance(key, str) and key and key not in mapping, "Row IDs must be unique text.")
        require(isinstance(group, str), "Group values must be text.")
        mapping[key] = group
        if group.strip():
            groups[group].append(key)
        else:
            empty.append(key)
    operations = {"row_count": len(cells), "distinct_nonempty": len(groups), "empty_ids": empty,
                  "two_row_groups": [k for k, v in groups.items() if len(v) == 2],
                  "two_row_group_count": sum(len(v) == 2 for v in groups.values()),
                  "groups": dict(groups), "row_to_group": mapping}
    return {**manifest, "state": "complete", "operations": operations}
