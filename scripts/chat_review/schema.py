"""Validate immutable evidence and exact delivery spans."""

from copy import deepcopy
from collections import Counter
from hashlib import sha256
import re

from tasks.P_agent.control.model import canonical_json, digest
from tasks.P_workspace.references import check, handles


class Invalid(ValueError):
    """An input violates its declared schema."""


class Incomplete(Exception):
    """Available records cannot establish the requested result."""


def require(condition, message):
    if not condition:
        raise Invalid(message)


def obj(value, required, optional=()):
    require(type(value) is dict, "Expected an object.")
    require(set(required) <= value.keys(), "Required fields are missing.")
    require(value.keys() <= set(required) | set(optional), "Unknown fields are present.")
    return value


def array(value):
    require(type(value) is list, "Expected an array.")
    return value


def string(value, empty=False):
    require(type(value) is str and (empty or bool(value.strip())), "Expected text.")
    return value


def integer(value, minimum=0):
    require(type(value) is int and value >= minimum, "Expected an integer within its bounds.")
    return value


def boolean(value):
    require(type(value) is bool, "Expected a boolean.")
    return value


def text_digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def hash_value(value):
    require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value), "Invalid SHA-256 digest.")
    return value


def filename(value):
    string(value)
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", value)
            and ".." not in value, "Invalid report filename.")
    return value


def unique(values):
    require(len(values) == len(set(values)), "Duplicate identities are present.")


def packet_digest(packet):
    value = deepcopy(packet)
    value["identity"].pop("packet_digest", None)
    return digest(value)


def texts(delivery):
    return {**{f["name"]: f["content"] for f in delivery["files"]},
            "<closing>": delivery["closing_answer"]["content"]}


def validate_delivery(value, packet=None):
    obj(value, ("files", "closing_answer"))
    for f in array(value["files"]):
        if "local_revision" in f:
            obj(f, ("name", "base_version", "base_digest", "local_revision", "digest", "content", "requirement_id"))
            string(f["local_revision"])
            require(packet is not None, "A replay requires its original packet.")
            original = {x["name"]: x for x in packet["delivery"]["files"]}.get(f["name"])
            requirements = {r["id"]: r for r in packet["coverage"]["requested"]}
            if original:
                require((f["base_version"], f["base_digest"]) == (original["version"], original["digest"]),
                        "Replay provenance differs from the original version.")
            else:
                require(f["base_version"] is None and f["base_digest"] is None,
                        "New files cannot claim workspace provenance.")
                require(f["requirement_id"] in requirements, "A new file requires an explicit requirement.")
            if f["requirement_id"] is not None:
                require(f["requirement_id"] in requirements, "Unknown output requirement.")
                requested = requirements[f["requirement_id"]].get("filename")
                require(requested in (None, f["name"]), "The requested filename differs.")
        else:
            obj(f, ("name", "version", "digest", "content"))
            integer(f["version"], 1)
            if packet is not None:
                require(f in packet["delivery"]["files"], "Changed bytes require a local revision.")
        filename(f["name"])
        string(f["content"], empty=True)
        require(f["digest"] == text_digest(f["content"]), "File digest differs from its bytes.")
    unique([f["name"] for f in value["files"]])
    closing = obj(value["closing_answer"], ("digest", "content"), ("message_idx",))
    string(closing["content"], empty=True)
    if "message_idx" in closing:
        integer(closing["message_idx"])
    require(closing["digest"] == text_digest(closing["content"]), "Closing digest differs from its bytes.")
    return value


def validate_packet(value):
    obj(value, ("schema_version", "identity", "request", "delivery", "citations", "evidence", "history", "coverage"))
    require(type(value["schema_version"]) is int and value["schema_version"] == 1, "Unknown packet schema.")
    identity = obj(value["identity"], ("owner", "session_id", "turn_id", "source_revision", "loaded_source_digest", "packet_digest"))
    for field in identity:
        string(identity[field])
    hash_value(identity["loaded_source_digest"])
    req = obj(value["request"], ("current", "task_state", "amendments"), ("prior_requests",))
    string(req["current"], empty=True)
    require(type(req["task_state"]) is dict, "Task state must be an object.")
    array(req["amendments"])
    request_texts = {identity["turn_id"]: req["current"]}
    for prior in array(req.get("prior_requests", [])):
        obj(prior, ("source_turn", "text"))
        string(prior["source_turn"])
        string(prior["text"], empty=True)
        require(prior["source_turn"] not in request_texts, "Repeated source request identity.")
        request_texts[prior["source_turn"]] = prior["text"]
    validate_delivery(value["delivery"])
    evidence_ids = []
    for item in array(value["evidence"]):
        obj(item, ("id", "kind", "content", "digest", "complete", "metadata"))
        evidence_ids.append(string(item["id"]))
        string(item["kind"])
        string(item["content"], empty=True)
        boolean(item["complete"])
        require(type(item["metadata"]) is dict, "Evidence metadata must be an object.")
        require(item["digest"] == text_digest(item["content"]), "Evidence digest differs from its bytes.")
    unique(evidence_ids)
    for entry in array(value["citations"]):
        obj(entry, ("id", "source_id", "kind", "status", "reference"), ("metadata",))
        string(entry["id"])
        require(entry["source_id"] in evidence_ids, "Citation source is absent.")
        require(entry["kind"] == "citation" and entry["status"] in ("ok", "error"), "Invalid citation state.")
        require(type(entry["reference"]) is dict, "Citation reference must be an object.")
    unique([c["id"] for c in value["citations"]])
    history = obj(value["history"], ("messages", "complete", "omissions"))
    boolean(history["complete"])
    for omission in array(history["omissions"]):
        string(omission)
    identities = []
    for m in array(history["messages"]):
        obj(m, ("thread_id", "idx", "run_id", "role", "content", "is_final", "metadata"))
        string(m["thread_id"])
        integer(m["idx"])
        string(m["run_id"])
        require(m["role"] in ("user", "assistant", "tool", "compaction"), "Invalid message role.")
        string(m["content"], empty=True)
        boolean(m["is_final"])
        require(type(m["metadata"]) is dict, "Message metadata must be an object.")
        identities.append((m["thread_id"], m["idx"]))
    unique(identities)
    coverage = obj(value["coverage"], ("requested", "available", "missing"))
    for r in array(coverage["requested"]):
        obj(r, ("id", "source_turn", "request_span", "description"), ("filename",))
        string(r["id"])
        string(r["source_turn"])
        string(r["description"])
        require(r["source_turn"] in request_texts, "Requirement span needs the original turn text.")
        span(r["request_span"], request_texts[r["source_turn"]])
        if r.get("filename") is not None:
            filename(r["filename"])
    unique([r["id"] for r in coverage["requested"]])
    array(coverage["missing"])
    require(array(coverage["available"]) == list(texts(value["delivery"])), "Available outputs differ from the delivery.")
    require(identity["packet_digest"] == packet_digest(value), "Packet digest differs from its input.")
    return value


def span(value, text):
    require(type(value) is list and len(value) == 2, "A span requires two character offsets.")
    start, end = value
    integer(start)
    integer(end, 1)
    require(start < end <= len(text), "Span exceeds the original text.")
    return start, end


def resolve_quote(finding, text):
    quote = string(finding["quote"])
    if "start" in finding or "end" in finding:
        require("start" in finding and "end" in finding, "Both offsets are required.")
        start, end = span([finding["start"], finding["end"]], text)
    else:
        positions = [i for i in range(len(text)) if text.startswith(quote, i)]
        if "occurrence" in finding:
            index = integer(finding["occurrence"])
            require(index < len(positions), "Quote occurrence does not exist.")
            start = positions[index]
        else:
            require(len(positions) == 1, "Quote requires an unambiguous exact location.")
            start = positions[0]
        end = start + len(quote)
    require(text[start:end] == quote, "Quote differs from its character slice.")
    return {**finding, "start": start, "end": end}


def review_scope(delivery, names=None, include_closing=True):
    files = delivery["files"]
    if names is not None:
        require(set(names) <= {f["name"] for f in files}, "Unknown scope file.")
        files = [f for f in files if f["name"] in names]
    return {"files": [{k: f[k] for k in ("name", "digest")} for f in files],
            "include_closing": include_closing}


def validate_review(value, packet, delivery, scope=None):
    value = deepcopy(value)
    obj(value, ("schema_version", "delivery_digest", "findings", "unresolved", "coverage"))
    require(type(value["schema_version"]) is int and value["schema_version"] == 1, "Unknown review schema.")
    require(value["delivery_digest"] == digest(delivery), "Review names a different delivery.")
    scope = scope or review_scope(delivery)
    obj(scope, ("files", "include_closing"))
    boolean(scope["include_closing"])
    expected = review_scope(delivery, [f["name"] for f in scope["files"]], scope["include_closing"])
    require(scope == expected, "Review scope names a different file revision.")
    targets = {f["name"] for f in scope["files"]}
    if scope["include_closing"]:
        targets.add("<closing>")
    content = texts(delivery)
    source_ids = {e["id"] for e in packet["evidence"]}
    whole = scope == review_scope(delivery)
    requirements = {r["id"]: r for r in packet["coverage"]["requested"]}
    normalized = []
    for f in array(value["findings"]):
        obj(f, ("id", "kind", "evidence_refs", "proposed_correction"),
            ("file", "quote", "start", "end", "occurrence", "requirement_id", "handle"))
        string(f["id"])
        string(f["proposed_correction"])
        require(set(array(f["evidence_refs"])) <= source_ids, "Finding names unavailable evidence.")
        require(f["kind"] in ("contradicted", "unsupported", "missing_output", "invalid_handle"), "Unknown defect kind.")
        if f["kind"] == "missing_output":
            require(whole, "Missing outputs are outside an intermediate review.")
            require(f.get("requirement_id") in requirements, "Missing output lacks an explicit requirement.")
            require(not set(f) & {"file", "quote", "start", "end", "occurrence", "handle"}, "Missing outputs cannot have a delivery span.")
            r = requirements[f["requirement_id"]]
            present = any(x.get("requirement_id") == r["id"] or x["name"] == r.get("filename") for x in delivery["files"])
            require(not present, "The required output is present.")
        else:
            require(f.get("file") in targets and "quote" in f, "Finding is outside its review scope.")
            require("requirement_id" not in f, "A spanned finding cannot name a missing output.")
            f = resolve_quote(f, content[f["file"]])
            if f["kind"] == "invalid_handle":
                require(f.get("handle") in {h for h, _ in handles(f["quote"])}, "Finding does not contain its handle.")
                require(re.fullmatch(r"\[\s*[DW]\d+(?:\s*,\s*[DW]\d+)*\s*\]", f["quote"]),
                        "A citation finding must quote its complete citation bracket.")
                original_text = content[f["file"]]
                without = original_text[:f["start"]] + "citation" + original_text[f["end"]:]
                before = Counter(h for h, _ in handles(original_text))
                after = Counter(h for h, _ in handles(without))
                require(before[f["handle"]] - after[f["handle"]] == 1,
                        "The quoted bracket is literal text, not a rendered citation.")
                bad, _ = check(f["file"], content[f["file"]], packet["citations"])
                require(f["handle"] in {x["handle"] for x in bad}, "The citation handle resolves.")
            else:
                require("handle" not in f, "Only a citation finding can name a handle.")
                require(bool(f["evidence_refs"]), "A factual finding needs an evidence basis.")
        normalized.append(f)
    unique([f["id"] for f in normalized])
    value["findings"] = normalized
    for u in array(value["unresolved"]):
        obj(u, ("target", "reason"))
        require(u["target"] in targets | source_ids, "Unknown unresolved target.")
        string(u["reason"])
    coverage = obj(value["coverage"], ("examined_files", "closing_examined", "unreviewed_regions"))
    names = array(coverage["examined_files"])
    unique(names)
    require(set(names) <= targets - {"<closing>"}, "Coverage names an unknown target.")
    boolean(coverage["closing_examined"])
    require(not coverage["closing_examined"] or scope["include_closing"], "Closing review exceeds scope.")
    for region in array(coverage["unreviewed_regions"]):
        obj(region, ("file", "reason"), ("span",))
        require(region["file"] in targets, "Unreviewed region exceeds scope.")
        string(region["reason"])
        if "span" in region:
            span(region["span"], content[region["file"]])
    return value


def review_complete(value, scope):
    return (not value["unresolved"] and not value["coverage"]["unreviewed_regions"]
            and set(value["coverage"]["examined_files"]) == {f["name"] for f in scope["files"]}
            and value["coverage"]["closing_examined"] == scope["include_closing"])


def validate_reference(value, packet, delivery):
    # Grading owns the reference schema to keep model validation independent of labels.
    from .grade import validate_reference_records
    return validate_reference_records(value, packet, delivery)
