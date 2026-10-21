"""Provide finite source-reviewed deliveries for regression checks."""

from copy import deepcopy
import pytest
from scripts.chat_review.schema import digest, packet_digest, text_digest, texts


def make_packet(report="The source lists Rome and Madrid.\n", closing="The report is ready."):
    source = "name,city\r\nAda,Rome\r\nBea,Madrid\r\n"
    packet = {"schema_version": 1,
              "identity": {"owner": "test-owner", "session_id": "test-session", "turn_id": "1",
                           "source_revision": "test", "loaded_source_digest": "a" * 64},
              "request": {"current": "Write cities.md.", "task_state": {}, "amendments": []},
              "delivery": {"files": [{"name": "cities.md", "version": 2, "content": report,
                                      "digest": text_digest(report)}],
                           "closing_answer": {"message_idx": 8, "content": closing, "digest": text_digest(closing)}},
              "citations": [],
              "evidence": [{"id": "cities", "kind": "table", "content": source, "digest": text_digest(source),
                            "complete": True, "metadata": {"reading": "header", "rows": 2}}],
              "history": {"messages": [], "complete": True, "omissions": []},
              "coverage": {"requested": [{"id": "req-cities", "source_turn": "1", "request_span": [0, 16],
                                          "description": "Write the city report.", "filename": "cities.md"}],
                           "available": ["cities.md", "<closing>"], "missing": []}}
    seal(packet)
    return packet


def seal(packet):
    packet["identity"]["packet_digest"] = packet_digest(packet)
    return packet


def reference_for(packet, delivery=None, labels=None):
    delivery = delivery or packet["delivery"]
    files = []
    for index, (name, text) in enumerate(texts(delivery).items()):
        cid = f"claim-{index}"
        claims = [{"id": cid, "span": [0, len(text)], "quote": text,
                   "label": (labels or {}).get(name, "supported"), "source_ids": ["cities"],
                   "reason": "The explicit fixture source and report receipt establish this assertion."}] if text else []
        files.append({"name": name, "digest": text_digest(text), "claims": claims,
                      "regions": [{"span": [0, len(text)], "kind": "assertion", "claim_ids": [cid],
                                   "coverage_basis": "The complete fixture assertion was source-reviewed."}] if text else []})
    reference = {"schema_version": 1, "reference_revision": 1, "author": "fixture author", "author_kind": "agent",
                 "review_date": "2026-10-21", "independent_review": None,
                 "packet_digest": packet["identity"]["packet_digest"], "delivery_digest": digest(delivery),
                 "source_digests": {e["id"]: e["digest"] for e in packet["evidence"]},
                 "required_outputs": [{"requirement_id": "req-cities", "name": "cities.md"}], "files": files}
    approve(reference)
    return reference


def approve(reference):
    reference["independent_review"] = None
    reference["independent_review"] = {"reviewer": "fixture source reviewer", "date": "2026-10-21",
                                       "source_digest": digest(reference["source_digests"]),
                                       "reference_digest": digest(reference)}
    return reference


def labels_for(reference):
    return {"schema_version": 1, "reference_digest": digest(reference),
            "delivery_digest": reference["delivery_digest"], "reviewer": "fixture adjudicator",
            "labels": [{"claim_id": c["id"], "label": c["label"], "reason": c["reason"]}
                       for f in reference["files"] for c in f["claims"]]}


def empty_review(packet, delivery=None):
    delivery = delivery or packet["delivery"]
    return {"schema_version": 1, "delivery_digest": digest(delivery), "findings": [], "unresolved": [],
            "coverage": {"examined_files": [f["name"] for f in delivery["files"]],
                         "closing_examined": True, "unreviewed_regions": []}}


@pytest.fixture
def packet():
    return make_packet()


@pytest.fixture
def config():
    return {"model": "fixture", "thinking": False, "max_tokens": 1000, "temperature": None,
            "response_format": "json_object", "connect_timeout": 2, "read_timeout": 10, "procedure": "fresh"}
