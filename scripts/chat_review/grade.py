"""Grade explicit source-reviewed classifications without a model client."""

from copy import deepcopy
from .schema import (array, boolean, digest, integer, obj, require, span, string,
                     text_digest, texts, unique, validate_delivery, validate_packet)
from tasks.P_workspace.references import check

LABELS = {"supported", "contradicted", "unsupported", "uncertain"}
KINDS = {"assertion", "qualified_uncertainty", "structural", "quoted_source"}


def validate_reference_records(value, packet, delivery):
    obj(value, ("schema_version", "reference_revision", "author", "author_kind", "review_date",
                "independent_review", "packet_digest", "delivery_digest", "source_digests",
                "required_outputs", "files"), ("computed_facts", "limits"))
    require(type(value["schema_version"]) is int and value["schema_version"] == 1, "Unknown reference schema.")
    integer(value["reference_revision"], 1)
    for k in ("author", "review_date"):
        string(value[k])
    require(value["author_kind"] in ("person", "agent"), "Unknown reference author kind.")
    if value["independent_review"] is not None:
        ir = obj(value["independent_review"], ("reviewer", "date", "source_digest", "reference_digest"))
        string(ir["reviewer"])
        string(ir["date"])
        require(ir["reviewer"] != value["author"], "Reference approval must name another reviewer.")
        unsigned = deepcopy(value)
        unsigned["independent_review"] = None
        require(ir["reference_digest"] == digest(unsigned), "Independent approval names a different reference.")
        require(ir["source_digest"] == digest(value["source_digests"]), "Independent source approval differs.")
    require(value["packet_digest"] == packet["identity"]["packet_digest"], "Reference names a different packet.")
    require(value["delivery_digest"] == digest(delivery), "Reference names a different delivery.")
    sources = {e["id"]: e for e in packet["evidence"]}
    require(value["source_digests"] == {k: e["digest"] for k, e in sources.items()}, "Reference sources differ.")
    requirements = {r["id"]: r for r in packet["coverage"]["requested"]}
    for r in array(value["required_outputs"]):
        obj(r, ("requirement_id", "name"))
        require(r["requirement_id"] in requirements, "Unknown output requirement.")
        string(r["name"])
        require(requirements[r["requirement_id"]].get("filename") in (None, r["name"]), "Reference changes the requested filename.")
    unique([r["requirement_id"] for r in value["required_outputs"]])
    require({r["requirement_id"] for r in value["required_outputs"]} == set(requirements), "Required output coverage is incomplete.")
    content = texts(delivery)
    all_claims = []
    for f in array(value["files"]):
        obj(f, ("name", "digest", "regions", "claims"))
        require(f["name"] in content, "Reference names an absent file.")
        text = content[f["name"]]
        require(f["digest"] == text_digest(text), "Reference file digest differs.")
        claims = {}
        for c in array(f["claims"]):
            obj(c, ("id", "span", "quote", "label", "source_ids", "reason"),
                ("context_spans", "source_quotes", "action_check"))
            string(c["id"])
            start, end = span(c["span"], text)
            require(text[start:end] == c["quote"], "Reference claim differs from its span.")
            require(c["label"] in LABELS, "Unknown support label.")
            string(c["reason"])
            require(set(array(c["source_ids"])) <= sources.keys(), "Claim names an absent source.")
            require(bool(c["source_ids"]) or "action_check" in c or c["label"] == "uncertain", "A support label needs a source basis.")
            for ctx in c.get("context_spans", []):
                obj(ctx, ("file", "span", "quote"))
                require(ctx["file"] in content, "Unknown claim context.")
                a, b = span(ctx["span"], content[ctx["file"]])
                require(content[ctx["file"]][a:b] == ctx["quote"], "Claim context differs from its span.")
            for quote in c.get("source_quotes", []):
                obj(quote, ("source_id", "span", "quote"))
                require(quote["source_id"] in c["source_ids"], "Quote is outside the claim sources.")
                source_text = sources[quote["source_id"]]["content"]
                a, b = span(quote["span"], source_text)
                require(source_text[a:b] == quote["quote"], "Source quotation differs.")
            if "action_check" in c:
                a = obj(c["action_check"], ("target", "changed"))
                require(a["target"] in content, "Unknown action target.")
                boolean(a["changed"])
            claims[c["id"]] = c
            all_claims.append(c["id"])
        previous_end = 0
        assigned = []
        for r in array(f["regions"]):
            obj(r, ("span", "kind", "claim_ids", "coverage_basis"))
            a, b = span(r["span"], text)
            require(a >= previous_end, "Reference regions overlap or are unordered.")
            previous_end = b
            require(r["kind"] in KINDS, "Unknown region kind.")
            string(r["coverage_basis"])
            array(r["claim_ids"])
            require(r["kind"] == "structural" or bool(r["claim_ids"]), "A factual region needs claims.")
            require(r["kind"] != "structural" or not r["claim_ids"], "Structural regions cannot discard claims.")
            for cid in r["claim_ids"]:
                require(cid in claims, "Region names an absent claim.")
                c = claims[cid]
                require(a <= c["span"][0] < c["span"][1] <= b, "Claim exceeds its reviewed region.")
                if r["kind"] == "quoted_source":
                    require(bool(c.get("source_quotes")), "Quoted source text requires an exact source match.")
                    require(any(q["quote"] == c["quote"] for q in c["source_quotes"]), "Quoted delivery text differs from the source quote.")
                assigned.append(cid)
        unique(assigned)
        require(set(assigned) == set(claims), "A claim has no reviewed region.")
    unique(all_claims)
    unique([f["name"] for f in value["files"]])
    return value


def inventory_delivery(delivery, reference):
    """Keep every nonblank line and record gaps in reference classifications."""
    classified = {f["name"]: f for f in reference["files"]}
    lines, claims, uncovered = [], [], []
    for name, text in texts(delivery).items():
        f = classified.get(name, {"regions": [], "claims": []})
        covered = bytearray(len(text))
        for r in f["regions"]:
            a, b = r["span"]
            covered[a:b] = b"\1" * (b - a)
        offset = 0
        for line in text.splitlines(keepends=True):
            if line.strip():
                region = {"file": name, "span": [offset, offset + len(line)], "quote": line}
                lines.append(region)
                if any(not covered[i] for i in range(offset, offset + len(line)) if not text[i].isspace()):
                    uncovered.append(region)
            offset += len(line)
        claims.extend({**c, "file": name} for c in f["claims"])
    return {"delivery_digest": digest(delivery), "lines": lines, "claims": claims,
            "uncovered": uncovered, "delivery": delivery}


def grade_delivery(inventory, reference, adjudication):
    """Use independent labels and preserve unresolved coverage."""
    obj(adjudication, ("schema_version", "reference_digest", "delivery_digest", "reviewer", "labels"))
    require(type(adjudication["schema_version"]) is int and adjudication["schema_version"] == 1, "Unknown adjudication schema.")
    require(adjudication["reference_digest"] == digest(reference), "Labels name a different reference.")
    require(adjudication["delivery_digest"] == inventory["delivery_digest"], "Labels name a different delivery.")
    string(adjudication["reviewer"])
    labels = {}
    for label in array(adjudication["labels"]):
        obj(label, ("claim_id", "label", "reason"))
        string(label["claim_id"])
        require(label["label"] in LABELS, "Unknown adjudication label.")
        string(label["reason"])
        require(label["claim_id"] not in labels, "Repeated adjudication claim.")
        labels[label["claim_id"]] = label
    require(labels.keys() <= {c["id"] for c in inventory["claims"]}, "Labels name unknown claims.")
    defects, unresolved, grades = [], list(inventory["uncovered"]), []
    if reference["author_kind"] == "agent" and reference["independent_review"] is None:
        unresolved.append({"reason": "Agent references require independent source review."})
    diff = inventory.get("delivery_diff")
    for c in inventory["claims"]:
        a = labels.get(c["id"])
        label = a["label"] if a else "uncertain"
        if a and label != c["label"]:
            unresolved.append({"claim_id": c["id"], "reason": "Reference and adjudication disagree."})
            label = c["label"] if c["label"] in ("unsupported", "contradicted") else "uncertain"
        if c.get("action_check"):
            target = c["action_check"]["target"]
            if diff is None:
                label = "uncertain"
            else:
                actual = diff["closing_changed"] if target == "<closing>" else target in diff["changed"] + diff["added"] + diff["removed"]
                if actual != c["action_check"]["changed"]:
                    label = "contradicted"
        grade = {**c, "label": label, "reviewer": adjudication["reviewer"],
                 "adjudication_reason": a["reason"] if a else "No adjudication label.",
                 "reference_revision": reference["reference_revision"]}
        grades.append(grade)
        if label in ("unsupported", "contradicted"):
            defects.append(grade)
        elif label == "uncertain":
            unresolved.append(grade)
    available = {f["name"] for f in inventory["delivery"]["files"]}
    for r in reference["required_outputs"]:
        if r["name"] not in available:
            defects.append({"kind": "missing_output", **r})
    defects.extend(inventory.get("citation_defects", []))
    unresolved.extend(inventory.get("missing_evidence", []))
    verdict = "delivery_fail" if defects else "review_incomplete" if unresolved else "delivery_pass"
    return {"schema_version": 1, "verdict": verdict, "delivery_digest": inventory["delivery_digest"],
            "reference_digest": digest(reference), "source_digests": reference["source_digests"],
            "claims": grades, "defects": defects, "unresolved": unresolved,
            "region_count": len(inventory["lines"])}


def grade(packet, delivery, reference, labels):
    validate_packet(packet)
    validate_delivery(delivery, packet)
    validate_reference_records(reference, packet, delivery)
    inventory = inventory_delivery(delivery, reference)
    from .replay import delivery_diff
    inventory["delivery_diff"] = delivery_diff(packet["delivery"], delivery)
    inventory["citation_defects"] = [finding for name, content in texts(delivery).items()
                                    for finding in check(name, content, packet["citations"])[0]]
    inventory["missing_evidence"] = packet["coverage"]["missing"]
    return grade_delivery(inventory, reference, labels)
