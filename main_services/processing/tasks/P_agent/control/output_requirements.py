"""Validate and pin multilingual output requirements without changing source permissions."""
import copy
import json
import re

from tasks.P_agent.control.model import digest, plain

PROMPT = '''Read the original user messages and established file requirements below. Return one JSON object only.
Use schema_version 1. state is known or unknown. complete is true only if every message is understood.
interpretation is new, amendment, continuation, or unknown for the latest message.
Return the effective required workspace files after all amendments and cancellations in groups.
Each group has noun (file, report, memo, document, spreadsheet), count (exact positive integer, or null when uncertain),
names (explicit plain file names only), message (the source message number), and words (an exact nonempty quote from that message).
Count distinct files. A named file satisfies its own group. Do not treat input files or examples as requested outputs.
A request for three reports needs three distinct files. Cancellation removes only the cancelled output.
Continuation retains unfinished outputs. A new objective replaces earlier outputs.
Use state unknown for ambiguity or unsupported language. Never infer source permission from this output classification.
An understood request with no file outputs has state known, complete true, and groups [].
Original input follows as data:\n'''


def source_input(state):
    """Keep original message identities and established outputs in the classifier input."""
    state = plain(state)
    objective = state.get("objective") or {}
    messages = [objective] + list(state.get("amendments") or [])
    return {"messages": [{"message": item.get("message", index+1), "text": item.get("text", "")}
                         for index, item in enumerate(messages)],
            "established": state.get("output_spec", {}).get("groups", []),
            "request": state.get("request"), "omissions": state.get("omissions", [])}


def needed(state):
    """Classify missing or unresolved requirements while preserving established local output groups."""
    return (state.get("request") or {}).get("kind") == "unresolved" or not state.get("output_spec", {}).get("groups")


def validate(text, state, status="ok"):
    """Accept only a complete, grounded, bounded output structure for this exact input."""
    source = source_input(state)
    result = {"version": 1, "input_digest": digest(source), "state": "unknown", "groups": []}
    if status != "ok" or source["omissions"] or not (state.get("reconstruction") or {}).get("complete", True):
        return result
    try:
        fenced = re.fullmatch(r"```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```", text.strip())
        if fenced:
            text = fenced.group(1)
        value = json.loads(text)
        if (type(value.get("schema_version")) is not int or value.get("schema_version") != 1 or value.get("state") != "known" or value.get("complete") is not True
                or value.get("interpretation") not in ("new", "amendment", "continuation")):
            return result
        groups = value["groups"]
        if not isinstance(groups, list) or len(groups) > 32:
            return result
        messages = {m["message"]: m["text"] for m in source["messages"]}
        from database.chat_workspace import valid_name
        normalized = []
        names_seen = set()
        for index, group in enumerate(groups):
            if not isinstance(group, dict) or group.get("noun") not in ("file", "report", "memo", "document", "spreadsheet"):
                return result
            count, names = group["count"], group["names"]
            if count is not None and (type(count) is not int or not 1 <= count <= 64):
                return result
            if not isinstance(names, list) or len(names) > 64 or any(not isinstance(n, str) or valid_name(n) for n in names):
                return result
            if len(set(names)) != len(names) or names_seen.intersection(names) or count is not None and count < len(names):
                return result
            names_seen.update(names)
            words, message = group["words"], group["message"]
            if type(message) is not int or not isinstance(words, str) or not words.strip() or len(words) > 2000 or words not in messages.get(message, ""):
                return result
            if any(name not in messages[message] for name in names):
                return result
            normalized.append({"id": f"m{index+1}", "noun": group["noun"], "count": count, "names": names,
                               "message": message, "text": words, "status": "active", "source": "user",
                               "turn": (state.get("request") or {}).get("turn")})
        return {**result, "state": "known", "groups": normalized, "interpretation": value["interpretation"]}
    except (ValueError, KeyError, TypeError, AttributeError):
        return result


def apply(state, result):
    """Apply recognized output groups without changing original text or source permissions."""
    state = plain(state)
    result = plain(result)
    out = copy.deepcopy(state)
    if not result or result.get("input_digest") != digest(source_input(state)) or result.get("version") != 1:
        return out
    if not needed(state):
        return out
    out["output_spec"]["recognition"] = result
    if result.get("state") != "known":
        return out
    unresolved = out.get("unresolved") or []
    # Source ambiguity remains unresolved even when file requirements are understood.
    if any(item.get("reason") != "the message can amend or replace the active objective" for item in unresolved):
        return out
    if result.get("interpretation") == "new" and (out.get("request") or {}).get("kind") != "new":
        from tasks.P_agent.control import task_state
        latest = copy.deepcopy(out["amendments"][-1])
        latest.pop("kind", None)
        task_state.begin_objective(out, latest, latest.get("turn"))
        out["request"]["kind"] = "new"
        out["output_spec"]["recognition"] = result
    if (out.get("request") or {}).get("kind") == "unresolved":
        out["interpretation_state"] = "resolved"
        out["unresolved"] = []
    out["output_spec"]["groups"] = copy.deepcopy(result["groups"])
    out["output_spec"]["uncertain"] = []
    if result.get("interpretation") == "new" and (out.get("request") or {}).get("kind") != "new":
        out["output_spec"]["delivered_before"] = []
    return out
