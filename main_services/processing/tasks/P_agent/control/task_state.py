"""The effective task of a turn: one versioned record of the objective, the amendments of
the person, the source rules and the requested outputs.

The coordinator derives the record once, when it pins the turn (`coordinator._pin`), and
stores it in the control record of the opening message as `control["task_state"]`. Every
handler reads that stored copy through `PolicyContext.task_state`, so a retry or a worker
restart reads the same interpretation. A later code or prompt change does not reinterpret a
pinned turn. The text task `control["task"]` (`text_task`) is derived from the record for
the readers of the text fields (`facts.task_of`, `facts.task_text`).

**Fields.** `schema_version` names the representation. `objective` is the active objective
and the turn that stated it. `request` gives the turn of the current message and how it was
read: `new`, `continuation`, `amendment` or `unresolved`. `amendments` holds the messages of
later turns that changed the active objective, in turn order. `source_rules` holds each
source permission and restriction with its turn, its character span and its status:
`active`, `superseded` (by a later turn) or `expired` (a rule for one task that a new
objective ended). `output_spec` holds the requested output groups. `interpretation_state` is
`resolved` or `unresolved`, and `unresolved` names each message that the rules below could
not classify. `omissions` names the evidence that the stored record leaves out because of
its bounds. `reconstruction` states how the earlier turns were read. `messages` counts the messages
that the record read, and each rule records the position of its message in `message`.

Every field holds the original words of a user message or of the structured board task, with
its turn and its span. A computed value never becomes a requirement of the person.

**Recognition.** Only the explicit forms below are recognized. Another message keeps its
original text, and the record is `unresolved`, so no handler presents an old restriction or
an old objective as the current instruction.

* A continuation only asks to continue, such as `Continue.` It keeps the active objective
  and its unfinished outputs.
* A permission (`You may now use the web.`) supersedes the earlier restrictions that it
  conflicts with. A later rule supersedes an earlier rule of the same subject. An exclusive
  restriction (`Use only the selected collections.`) also forbids the web.
* A cancellation (`Skip the second report.`) removes one output of an identified group, or
  the whole group. A cancellation that identifies no group is unresolved.
* An amendment holds only rules, cancellations, continuations and output requests that refer
  to the earlier work (`Now write it as a file.`). It keeps the active objective.
* A short follow-up question (`And the second one?`) is unresolved. Its text becomes the
  objective, and the earlier objective stays recorded beside it.
* Another message starts a new objective. It keeps the session rules and drops the outputs
  of the earlier objective.

**Outputs.** An output group comes from one affirmative output clause: an output verb with a
file noun (`write two memos`), a file destination (`in a short report`) or a file name
(`save it as notes.md`). A file name after an input word (`from input.csv`) is an input. A
negated clause (`Do not write a report.`), a quoted span and an example (`for example`) are
no output. A clause after `if` gives an uncertain group, which loads the report skill and
counts as no requirement. A count is exact only when the clause states it (`a`, `two`, `3`)
or names the files. A plural noun without a count, `several` and an upper bound (`up to
three`) give no exact count. The names of the clause of a counted group belong to that group.
A file name that a later clause gives to `it` names the output of the previous group. A
structured deliverable gives its count from its own words (`Three reports`).
"""

from __future__ import annotations

import copy
import re
from typing import Any, Iterable, Mapping, Optional

SCHEMA_VERSION = 1

#: The bounds of the stored record. A cut is named in `omissions`.
MAX_ITEM_CHARS = 2000
MAX_OBJECTIVE_CHARS = 8000
MAX_AMENDMENTS = 32
MAX_RULES = 64
MAX_GROUPS = 32
MAX_DELIVERED = 64

#: The kinds of a request.
NEW, CONTINUATION, AMENDMENT, UNRESOLVED = "new", "continuation", "amendment", "unresolved"

# ------------------------------------------------------------------------- sentences


def spans(text: str) -> list[tuple[int, int, str]]:
    """The sentences of `text` with their character spans. A full stop inside a file name
    does not end a sentence."""
    out = []
    for match in re.finditer(r"[^\n]+", text or ""):
        line, base = match.group(0), match.start()
        start = 0
        for end in re.finditer(r"[.!?]+(?=\s|$)", line):
            piece = line[start:end.end()]
            if piece.strip():
                lead = len(piece) - len(piece.lstrip())
                out.append((base + start + lead, base + end.end(), piece.strip()))
            start = end.end()
        piece = line[start:]
        if piece.strip():
            lead = len(piece) - len(piece.lstrip())
            out.append((base + start + lead, base + len(line), piece.strip()))
    return out


def _blank_quotes(text: str) -> str:
    """`text` with quoted spans and code spans replaced by spaces of equal length."""
    def blank(match):
        return " " * len(match.group(0))
    text = re.sub(r"`[^`]*`", blank, text)
    text = re.sub(r"(?<![\w])\"[^\"\n]*\"", blank, text)
    text = re.sub(r"(?<![\w])'[^'\n]*'(?![\w])", blank, text)
    text = re.sub("“[^”\n]*”", blank, text)
    return text


# --------------------------------------------------------------------------- outputs

FILE_NOUNS = (r"(?:reports?|files?|memos?|documents?|dossiers?|briefs?|briefing\s+notes?|"
              r"write-?ups?|markdown(?:\s+files?)?|spreadsheets?|csv\s+files?)")
FILE_NAME = r"[\w][\w-]*(?:\.[\w-]+)*\.(?:md|markdown|txt|csv|json|html)"
COUNT_WORDS = {"a": 1, "an": 1, "one": 1, "single": 1, "two": 2, "three": 3, "four": 4,
               "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
COUNT = r"(?:a|an|one|two|three|four|five|six|seven|eight|nine|ten|\d{1,2}|several|separate|single)"
#: The words that can stand between a count and a file noun.
MODIFIERS = (r"(?:short|brief|new|separate|markdown|workspace|single|small|concise|detailed|final|"
             r"plain|text|one-page|written|full|summary|cited|sourced)")
#: An output verb with its file noun: "write a report", "draft two short memos".
OUTPUT_ACTION = re.compile(
    r"\b(?P<verb>write|create|draft|prepare|produce|compose|compile|generate|make|save|deliver|export|put\s+together)"
    r"\s+(?:(?:me|us)\s+)?(?:(?P<bound>up\s+to|at\s+most|no\s+more\s+than)\s+)?"
    r"(?:(?P<count>" + COUNT + r"|the|this|these|my|our)\s+)?"
    r"(?:(?!(?:of|in|on|about|from|for|with|that|which|the|to|as)\b)[\w-]+\s+){0,3}?"
    r"(?P<noun>" + FILE_NOUNS + r")\b", re.IGNORECASE)
#: A file destination after an output verb: "put the results in a file", "write the
#: counts in a short report".
FILE_DESTINATION = re.compile(
    r"\b(?P<verb>write|put|save|store|place|list|record|collect|keep|summari[sz]e|export|output|give|return|compile|split)\b"
    r"[^.!?\n]{0,60}?\b(?:in|into|to|as)\s+(?:(?P<count>" + COUNT + r")\s+)?"
    r"(?:" + MODIFIERS + r"\s+){0,2}(?P<noun>files?|reports?|documents?|memos?)\b", re.IGNORECASE)
#: A named output path: "save it as notes.md", "write summary.md".
NAMED_OUTPUT = re.compile(
    r"\b(?P<verb>save|write|create|export|store|put|produce|name|call)\b[^.!?\n]{0,60}?\b(?P<name>" + FILE_NAME + r")\b",
    re.IGNORECASE)
#: A second counted noun of one clause: "write two memos and three reports".
CONJOINED = re.compile(r"\s*,?\s*\band\s+(?P<count>" + COUNT + r")\s+(?:" + MODIFIERS + r"\s+){0,2}(?P<noun>"
                       + FILE_NOUNS + r")\b", re.IGNORECASE)
ANY_FILE_NAME = re.compile(r"\b" + FILE_NAME + r"\b", re.IGNORECASE)
NEGATION = re.compile(
    r"\b(?:do\s+not|don'?t|does\s+not|doesn'?t|never|no\s+need\s+to|without|must\s+not|mustn'?t|"
    r"should\s+not|shouldn'?t|not|cannot|can'?t|avoid|instead\s+of)\b(?:\s+\w+){0,2}\s*$", re.IGNORECASE)
EXAMPLE = re.compile(r"\b(?:for\s+example|for\s+instance|e\.g\.|such\s+as)\b", re.IGNORECASE)
CONDITIONAL = re.compile(r"\b(?:if|unless|in\s+case)\b", re.IGNORECASE)
#: The words after which a file name is an input, and after which it is an output again.
INPUT_WORDS = {"from", "using", "of", "on", "about", "with", "read", "reading", "based", "open"}
OUTPUT_WORDS = {"as", "to", "into", "named", "called", "write", "save", "create", "export", "store",
                "produce", "put"}
ANAPHORA = re.compile(r"\b(?:it|this|that|them|these|those|the\s+(?:report|file|memo|document|answer|"
                      r"results?|findings?|list|counts?|table|summary|draft))\b", re.IGNORECASE)


def _noun(text: str) -> str:
    """The singular base of a file noun, such as `report` for `short reports`."""
    word = re.sub(r"\s+", " ", (text or "").lower()).strip()
    for base in ("briefing note", "spreadsheet", "dossier", "document", "report", "memo",
                 "brief", "file"):
        if base in word:
            return base
    if "write" in word:
        return "write-up"
    return "file"


def _plural(noun: str) -> bool:
    return bool(re.search(r"s\s*$", noun or "")) and not re.search(r"(?:brief|ss)\s*$", noun or "", re.I)


def _count(word: str, noun: str, bound: str = "") -> Optional[int]:
    """The exact count that a count word gives, or None."""
    word = (word or "").lower()
    if bound:
        return None
    if word in COUNT_WORDS:
        return COUNT_WORDS[word]
    if word.isdigit():
        return int(word)
    if word in ("", "the", "this", "my", "our") and not _plural(noun):
        return 1
    return None


def _segment_names(text: str, start: int, end: int) -> list[str]:
    """The output file names of `text[start:end]`, an output clause. A name after an input
    word is an input, until an output word follows."""
    outputs = []
    mode = "output"
    for token in re.finditer(FILE_NAME + r"|[\w'-]+", text[start:end], re.IGNORECASE):
        word = token.group(0)
        if ANY_FILE_NAME.fullmatch(word):
            if mode == "output":
                outputs.append(word)
            continue
        lower = word.lower()
        if lower in OUTPUT_WORDS:
            mode = "output"
        elif lower in INPUT_WORDS:
            mode = "input"
    return outputs


def _clause_matches(clean: str) -> list[dict]:
    """The output clauses of one sentence with quotes removed, in verb order. The patterns
    that start at one verb give one clause."""
    found: dict[int, dict] = {}
    for pattern in (OUTPUT_ACTION, FILE_DESTINATION, NAMED_OUTPUT):
        for match in pattern.finditer(clean):
            verb = match.start("verb")
            item = found.setdefault(verb, {"start": verb, "end": match.end(), "count": None,
                                           "noun": "", "counted": False, "bound": ""})
            item["end"] = max(item["end"], match.end())
            groups = match.groupdict()
            if groups.get("noun") and not item["counted"]:
                item["noun"] = groups["noun"]
                item["bound"] = groups.get("bound") or ""
                item["count"] = _count(groups.get("count") or "", groups["noun"], item["bound"])
                item["counted"] = True
    return [found[k] for k in sorted(found)]


def _affirmative(clean: str, clauses: list[dict]) -> list[dict]:
    return [c for c in clauses if not NEGATION.search(clean[:c["start"]][-40:])]


def output_groups(text: str, turn: Optional[int], source: str = "user",
                  first_id: int = 1) -> tuple[list[dict], list[dict]]:
    """The output groups and the uncertain groups that `text` requests, in text order."""
    groups: list[dict] = []
    uncertain: list[dict] = []
    for s_start, _s_end, sentence in spans(text):
        clean = _blank_quotes(sentence)
        if EXAMPLE.search(clean):
            continue
        clauses = _affirmative(clean, _clause_matches(clean))
        for position, clause in enumerate(clauses):
            limit = clauses[position + 1]["start"] if position + 1 < len(clauses) else len(clean)
            names = list(dict.fromkeys(_segment_names(clean, clause["start"], limit)))
            items = [(clause["count"], clause["noun"], clause["counted"], clause["bound"])]
            for extra in CONJOINED.finditer(clean[clause["end"]:limit]):
                items.append((_count(extra.group("count"), extra.group("noun")), extra.group("noun"), True, ""))
            evidence = {"turn": turn, "source": source, "start": s_start + clause["start"],
                        "end": s_start + limit, "text": sentence[clause["start"]:limit].strip()[:MAX_ITEM_CHARS]}
            for index, (count, noun, counted, bound) in enumerate(items):
                own = names if index == 0 else []
                if not own and not counted:
                    continue
                if own:
                    count = (len(own) if not bound else None) if count is None else max(count, len(own))
                # A names-only clause that refers back names the output of the last group.
                if (not counted and own and groups and ANAPHORA.search(clean[clause["start"]:limit])
                        and groups[-1]["count"] is not None and len(groups[-1]["names"]) < groups[-1]["count"]):
                    target = groups[-1]
                    target["names"] = list(dict.fromkeys(target["names"] + own))[:target["count"]]
                    target["evidence"].append(dict(evidence))
                    continue
                group = {"names": own, "count": count, "noun": _noun(noun) if noun else "file",
                         "role": "file", "status": "active", "cancelled": [],
                         "evidence": [dict(evidence)]}
                (uncertain if CONDITIONAL.search(clean[:clause["start"]]) else groups).append(group)
    for number, group in enumerate(groups, start=first_id):
        group["id"] = f"g{number}"
    return groups, uncertain


def structured_groups(items: Iterable[Mapping], turn: Optional[int], first_id: int = 1) -> list[dict]:
    """The output groups of the deliverables of a structured task: one for each item that
    names a file noun or a file name. The count comes from the words of the item."""
    groups = []
    for item in items:
        text = str(item.get("text") or "")
        clean = _blank_quotes(text)
        names = list(dict.fromkeys(ANY_FILE_NAME.findall(clean)))
        noun = re.search(r"(?:\b(?P<count>" + COUNT + r")\s+(?:" + MODIFIERS + r"\s+){0,2})?(?P<noun>"
                         + FILE_NOUNS + r")\b", clean, re.IGNORECASE)
        if not names and not noun:
            continue
        count = _count(noun.group("count") or "", noun.group("noun")) if noun else None
        if names:
            count = max(count or 0, len(names))
        groups.append({"names": names, "count": count,
                       "noun": _noun(noun.group("noun")) if noun else "file", "role": "file",
                       "status": "active", "cancelled": [],
                       "evidence": [{"turn": item.get("turn", turn), "source": str(item.get("source") or ""),
                                     "start": 0, "end": len(text), "text": text[:MAX_ITEM_CHARS]}]})
    for number, group in enumerate(groups, start=first_id):
        group["id"] = f"g{number}"
    return groups


# ----------------------------------------------------------------------------- rules

SOURCE_RESTRICTION = re.compile(
    r"\b(?:only|just|exclusively|solely|limit(?:ed)? (?:it |this |yourself |the search )?to|restrict(?:ed)?(?: it| this| yourself)? to|stick to|"
    r"do not|don't|never|without|except|exclud(?:e|ing)|must not|no)\b[^.!?\n]{0,80}?"
    r"\b(?:collections?|datasets?|folders?|documents?|e-?mails?|files?|archives?|web|internet|online|"
    r"websites?|sites?|sources?|google|search engines?|news)\b", re.IGNORECASE)
PERMISSION = re.compile(
    r"\b(?:you\s+(?:may|can|are\s+allowed\s+to|are\s+free\s+to|are\s+permitted\s+to)|fe{2}l\s+free\s+to|"
    r"it\s+is\s+(?:fine|ok(?:ay)?|allowed)\s+to|go\s+ahead\s+and|please|now|also)\s+(?:now\s+|also\s+)?"
    r"(?:use|search|browse|check|consult|read|look\s+(?:at|on))\b[^.!?\n]{0,60}?"
    r"\b(?:web|internet|online|websites?|google|news|public\s+sources?)\b"
    r"|\b(?:web|internet)(?:\s+(?:search(?:es)?|use|access|sources?))?\s+(?:is|are)\s+(?:now\s+)?"
    r"(?:allowed|permitted|fine|ok(?:ay)?)\b"
    r"|\buse\s+the\s+(?:web|internet)\s+(?:as\s+well|too|also)\b", re.IGNORECASE)
WEB_WORDS = re.compile(r"\b(?:web|internet|online|websites?|sites?|google|search engines?|news|public sources?)\b", re.I)
EXCLUSIVE = re.compile(r"\b(?:only|just|exclusively|solely|limit(?:ed)?\b[^.!?\n]{0,30}\bto|"
                       r"restrict(?:ed)?\b[^.!?\n]{0,30}\bto|stick to)\b", re.I)
TASK_SCOPE = re.compile(r"\b(?:for\s+this\s+(?:one|question|task|request|answer)|this\s+time|for\s+now)\b", re.I)


def source_rules(text: str, turn: Optional[int], source: str = "user") -> list[dict]:
    """The source permissions and restrictions of `text`, in text order."""
    out = []
    for start, end, sentence in spans(text):
        clean = _blank_quotes(sentence)
        permission = PERMISSION.search(clean)
        restriction = None if permission else SOURCE_RESTRICTION.search(clean)
        if not permission and not restriction:
            continue
        subject = "web" if permission or WEB_WORDS.search(restriction.group(0)) else "collections"
        out.append({"text": sentence[:MAX_ITEM_CHARS], "turn": turn, "source": source,
                    "start": start, "end": end, "subject": subject,
                    "effect": "allow" if permission else "restrict",
                    "exclusive": bool(restriction and EXCLUSIVE.search(clean)),
                    "scope": "task" if TASK_SCOPE.search(clean) else "session",
                    "status": "active", "superseded_by": None})
    return out


def _forbids(rule: Mapping) -> set:
    """The subjects that a rule forbids."""
    if rule.get("effect") != "restrict":
        return set()
    if rule.get("exclusive"):
        return {"web"} if rule.get("subject") == "collections" else {"collections"}
    return {rule.get("subject")}


def _apply_rules(state: dict, new: list[dict]) -> None:
    """Add the rules of a later turn. Each one supersedes the active rules of earlier turns
    that it replaces or conflicts with."""
    for rule in new:
        for old in state["source_rules"]:
            if old["status"] != "active" or old.get("message") == rule.get("message"):
                continue
            # A narrower restriction of the collections keeps an exclusive one, whose web
            # prohibition it does not state.
            replaces = old["subject"] == rule["subject"] and not (
                old["effect"] == rule["effect"] == "restrict" and old["exclusive"] and not rule["exclusive"])
            conflicts = ((rule["effect"] == "allow" and rule["subject"] in _forbids(old))
                         or (old["effect"] == "allow" and old["subject"] in _forbids(rule)))
            if replaces or conflicts:
                old["status"], old["superseded_by"] = "superseded", rule.get("turn")
        state["source_rules"].append(rule)


def source_scope(state: Optional[Mapping]) -> dict:
    """`allowed`, `forbidden` or `unstated` for the web and for the collections, from the
    active rules of the record."""
    scope = {"web": "unstated", "collections": "unstated"}
    for rule in (state or {}).get("source_rules") or []:
        if rule.get("status") != "active":
            continue
        if rule.get("effect") == "allow":
            scope[rule["subject"]] = "allowed"
        for subject in _forbids(rule):
            scope[subject] = "forbidden"
    return scope


# ----------------------------------------------------------------------- the request

CONTINUE = re.compile(
    r"^(?:(?:ok(?:ay)?|yes|sure|thanks|thank\s+you|good|great|fine)[,.!\s]+)?(?:please\s+)?"
    r"(?:continue|go\s+on|keep\s+going|carry\s+on|proceed|resume|go\s+ahead|finish(?:\s+(?:it|the\s+task|the\s+work|up))?)"
    r"(?:\s+(?:with\s+(?:it|that|the\s+task|the\s+work|the\s+rest)|please|then|now))*\s*[.!]*$", re.IGNORECASE)
CANCEL = re.compile(
    r"^(?:(?:ok(?:ay)?|actually|also|and|now|please|instead)[,\s]+)*(?:skip|drop|cancel|omit|forget(?:\s+about)?|leave\s+out|remove|"
    r"no\s+need\s+for|do\s+not\s+(?:write|create|make|produce)|don'?t\s+(?:write|create|make|produce))\s+"
    r"(?:the\s+|a\s+|an\s+)?(?:(?P<ordinal>first|second|third|fourth|fifth|sixth|last|\d+(?:st|nd|rd|th))\s+)?"
    r"(?:" + MODIFIERS + r"\s+)?(?:(?P<noun>" + FILE_NOUNS + r")|(?P<name>" + FILE_NAME + r"))\b", re.IGNORECASE)
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6}
FOLLOW_UP = re.compile(r"^(?:and|also|now|then|what\s+about|how\s+about|same\s+for)\b", re.I)
#: The words of an output request that refers to the earlier work and adds no subject.
FILLER = {"now", "please", "also", "then", "and", "it", "this", "that", "them", "these", "those", "the",
          "a", "an", "as", "in", "into", "to", "for", "me", "us", "results", "result", "answer",
          "findings", "finding", "list", "counts", "count", "table", "summary", "draft", "too",
          "instead", "again", "all", "file", "files", "report", "reports", "memo", "memos",
          "with", "your", "our", "my", "same", "just", "separate", "short", "new", "one", "two",
          "three", "four", "five", "six", "seven", "eight", "nine", "ten", "each", "markdown",
          "ok", "okay", "write", "save", "put", "create", "make", "draft", "prepare", "of"}


def _sentence_kind(sentence: str, has_groups: bool) -> str:
    """One of `continue`, `rule`, `cancel`, `follow` (an output request that refers to the
    earlier work), `output` or `content`."""
    clean = _blank_quotes(sentence).strip()
    if CONTINUE.match(clean):
        return "continue"
    if has_groups and CANCEL.match(clean):
        return "cancel"
    clauses = _affirmative(clean, _clause_matches(clean))
    if source_rules(sentence, None) and not clauses:
        return "rule"
    if clauses:
        rest = ANY_FILE_NAME.sub(" ", clean)
        words = [w for w in re.findall(r"[a-z][a-z'-]*", rest.lower()) if w not in FILLER]
        return "follow" if not words else "output"
    return "content"


def classify(request: str, has_objective: bool, has_groups: bool) -> str:
    """How a message changes the task: `new`, `continuation`, `amendment` or `unresolved`."""
    sentences = [s for _a, _b, s in spans(request)]
    if not has_objective or not sentences:
        return NEW
    kinds = [_sentence_kind(s, has_groups) for s in sentences]
    if all(k == "continue" for k in kinds):
        return CONTINUATION
    if all(k in ("continue", "rule", "cancel", "follow") for k in kinds):
        return AMENDMENT
    if FOLLOW_UP.match(request.strip()) and len(re.findall(r"\w+", request)) <= 15 and "output" not in kinds:
        return UNRESOLVED
    return NEW


def _cancel(state: dict, sentence: str, turn: Optional[int]) -> bool:
    """Apply one cancellation to the active groups. False when it identifies no group."""
    match = CANCEL.match(_blank_quotes(sentence).strip())
    if not match:
        return False
    groups = [g for g in state["output_spec"]["groups"] if g["status"] == "active"]
    record = {"turn": turn, "text": sentence[:MAX_ITEM_CHARS]}
    if match.group("name"):
        name = match.group("name")
        owners = [g for g in groups if name in g["names"]]
        if len(owners) != 1:
            return False
        group = owners[0]
        group["names"] = [n for n in group["names"] if n != name]
        group["count"] = max(0, int(group["count"] or 1) - 1)
        group["cancelled"].append({**record, "name": name})
        if group["count"] == 0:
            group["status"] = "cancelled"
        return True
    noun = _noun(match.group("noun"))
    owners = [g for g in groups if g["noun"] == noun]
    if len(owners) != 1:
        return False
    group = owners[0]
    ordinal = (match.group("ordinal") or "").lower()
    if not ordinal and (_plural(match.group("noun")) or group["count"] == 1):
        group["status"] = "cancelled"
        group["cancelled"].append(record)
        return True
    count = group["count"]
    if ordinal == "last":
        number = count or 0
    else:
        number = ORDINALS.get(ordinal) or (int(re.sub(r"\D", "", ordinal)) if ordinal else 0)
    if not count or not number or number > count:
        return False
    if group["names"] and number <= len(group["names"]):
        record["name"] = group["names"][number - 1]
        group["names"] = group["names"][:number - 1] + group["names"][number:]
    group["count"] = count - 1
    group["cancelled"].append({**record, "item": number})
    if group["count"] == 0:
        group["status"] = "cancelled"
    return True


# ----------------------------------------------------------------------- the record


def empty() -> dict:
    """A record without an objective."""
    return {"schema_version": SCHEMA_VERSION, "objective": None, "request": None,
            "amendments": [], "source_rules": [], "output_spec": _new_spec(),
            "interpretation_state": "resolved", "unresolved": [], "omissions": [],
            "reconstruction": {"turns_read": 0, "complete": True, "source": "none"}}


def _new_spec() -> dict:
    return {"groups": [], "uncertain": [], "delivered_before": []}


def _omit(state: dict, field: str, count: int, reason: str, turn: Optional[int] = None) -> None:
    if count > 0:
        state["omissions"].append({"field": field, "count": count, "reason": reason,
                                   **({"turn": turn} if turn is not None else {})})


def _bounded(state: dict, field: str, text: str, limit: int, turn: Optional[int]) -> str:
    if len(text) > limit:
        _omit(state, field, len(text) - limit, "characters beyond the stored excerpt", turn)
        return text[:limit]
    return text


def _next_group_id(state: dict) -> int:
    used = [int(g["id"][1:]) for g in state["output_spec"]["groups"]
            if re.fullmatch(r"g\d+", str(g.get("id", "")))]
    return max(used, default=0) + 1


def derive(request: str, turn: Optional[int], base: Optional[Mapping] = None,
           source: str = "user") -> dict:
    """The record of a turn whose message is `request`, after the record `base` of the
    earlier turns. `base` stays unchanged."""
    state = copy.deepcopy(dict(base)) if base else empty()
    request = request or ""
    active = [g for g in state["output_spec"]["groups"] if g["status"] == "active"]
    kind = classify(request, bool(state.get("objective")), bool(active))
    state["request"] = {"turn": turn, "kind": kind}
    # The position of the message in the record, so rules of one message never supersede
    # each other, also for an older turn whose number is unknown.
    message = state["messages"] = int(state.get("messages") or 0) + 1
    objective = {"text": request, "turn": turn, "source": source, "message": message}
    if kind == NEW:
        objective["text"] = _bounded(state, "objective", request, MAX_OBJECTIVE_CHARS, turn)
        state.update(objective=objective, amendments=[], output_spec=_new_spec(),
                     interpretation_state="resolved", unresolved=[])
        state.pop("earlier_objective", None)
        for rule in state["source_rules"]:
            if rule["status"] == "active" and rule.get("scope") == "task":
                rule["status"], rule["superseded_by"] = "expired", turn
    elif kind == UNRESOLVED:
        objective["text"] = _bounded(state, "objective", request, MAX_OBJECTIVE_CHARS, turn)
        earlier_groups = state["output_spec"]["groups"]
        state.update(earlier_objective=state["objective"], objective=objective,
                     interpretation_state="unresolved",
                     output_spec={**_new_spec(), "earlier_groups": earlier_groups})
        state["unresolved"].append({"turn": turn, "text": request[:MAX_ITEM_CHARS],
                                    "reason": "a short follow-up can continue or replace the earlier objective"})
    else:
        state["amendments"].append({"text": _bounded(state, "amendments", request, MAX_ITEM_CHARS, turn),
                                    "turn": turn, "source": source, "kind": kind, "message": message})
        if len(state["amendments"]) > MAX_AMENDMENTS:
            _omit(state, "amendments", len(state["amendments"]) - MAX_AMENDMENTS,
                  "the oldest amendments beyond the stored bound")
            state["amendments"] = state["amendments"][-MAX_AMENDMENTS:]
    _apply_rules(state, [{**rule, "message": message} for rule in source_rules(request, turn, source)])
    if kind != CONTINUATION:
        if kind == AMENDMENT:
            for _a, _b, sentence in spans(request):
                if _sentence_kind(sentence, True) == "cancel" and not _cancel(state, sentence, turn):
                    state["interpretation_state"] = "unresolved"
                    state["unresolved"].append({"turn": turn, "text": sentence[:MAX_ITEM_CHARS],
                                                "reason": "the cancellation identifies no requested output"})
        groups, uncertain = output_groups(request, turn, source, _next_group_id(state))
        state["output_spec"]["groups"].extend(groups)
        state["output_spec"]["uncertain"].extend(uncertain)
    _bound_lists(state)
    return state


def _bound_lists(state: dict) -> None:
    rules = state["source_rules"]
    if len(rules) > MAX_RULES:
        inactive = [r for r in rules if r["status"] != "active"]
        drop = min(len(rules) - MAX_RULES, len(inactive))
        dropped = {id(r) for r in inactive[:drop]}
        state["source_rules"] = [r for r in rules if id(r) not in dropped]
        _omit(state, "source_rules", drop, "the oldest inactive rules beyond the stored bound")
    spec = state["output_spec"]
    if len(spec["groups"]) > MAX_GROUPS:
        _omit(state, "output_spec", len(spec["groups"]) - MAX_GROUPS, "output groups beyond the stored bound")
        spec["groups"] = spec["groups"][:MAX_GROUPS]
    if len(spec["delivered_before"]) > MAX_DELIVERED:
        _omit(state, "output_spec", len(spec["delivered_before"]) - MAX_DELIVERED,
              "delivered files beyond the stored bound")
        spec["delivered_before"] = spec["delivered_before"][-MAX_DELIVERED:]


def record_delivery(state: dict, files: Iterable[Mapping], turn: Optional[int]) -> dict:
    """Add the files that an earlier turn of the active objective delivered."""
    delivered = state["output_spec"]["delivered_before"]
    known = {(d["name"], d.get("version")) for d in delivered}
    for item in files:
        key = (str(item.get("name") or ""), item.get("version"))
        if key[0] and key not in known:
            delivered.append({"name": key[0], "version": key[1], "turn": turn})
            known.add(key)
    _bound_lists(state)
    return state


def _items(task: Mapping, key: str) -> list[dict]:
    value = task.get(key) if isinstance(task, Mapping) else None
    if isinstance(value, Mapping):
        return [dict(value)] if isinstance(value.get("text"), str) else []
    if isinstance(value, (list, tuple)):
        return [dict(v) for v in value if isinstance(v, Mapping) and isinstance(v.get("text"), str)]
    return []


def from_structured(task: Mapping[str, Any], turn: Optional[int] = None, legacy: bool = False) -> dict:
    """The record of a structured task: a board explore task, or the text task of a turn
    pinned before this record existed (`legacy`). Its fields stay authoritative. A
    deliverable names the outputs, and then the objective and the corrections add none."""
    state = empty()
    objective = (_items(task, "objective") or [{"text": "", "source": "user"}])[0]
    turn = objective.get("turn", turn)
    state["objective"] = {"text": _bounded(state, "objective", objective["text"], MAX_OBJECTIVE_CHARS, turn),
                          "turn": turn, "source": str(objective.get("source") or "user")}
    state["request"] = {"turn": turn, "kind": NEW}
    state["reconstruction"] = {"turns_read": 0, "complete": not legacy,
                               "source": "legacy" if legacy else "structured"}
    spec = state["output_spec"]
    spec["groups"].extend(structured_groups(_items(task, "deliverables"), turn))
    if not spec["groups"]:
        for item in [objective] + _items(task, "corrections") + _items(task, "amendments"):
            found, uncertain = output_groups(item["text"], item.get("turn", turn),
                                             str(item.get("source") or ""), _next_group_id(state))
            spec["groups"].extend(found)
            spec["uncertain"].extend(uncertain)
    for key, effect in (("constraints", "restrict"), ("allowed_sources", "allow")):
        for item in _items(task, key):
            rules = source_rules(item["text"], item.get("turn"), str(item.get("source") or ""))
            state["source_rules"].extend(rules or [{
                "text": item["text"][:MAX_ITEM_CHARS], "turn": item.get("turn"),
                "source": str(item.get("source") or ""), "start": 0, "end": len(item["text"]),
                "subject": "web" if WEB_WORDS.search(item["text"]) else "collections",
                "effect": effect, "exclusive": False, "scope": "session", "status": "active",
                "superseded_by": None}])
    for item in _items(task, "amendments"):
        state["amendments"].append({"text": item["text"][:MAX_ITEM_CHARS], "turn": item.get("turn"),
                                    "source": str(item.get("source") or "user"), "kind": AMENDMENT})
    _bound_lists(state)
    return state


def _field(item: Mapping) -> dict:
    out = {"text": str(item.get("text") or ""), "source": str(item.get("source") or "user")}
    if isinstance(item.get("turn"), int) and not isinstance(item.get("turn"), bool):
        out["turn"] = item["turn"]
    return out


def _without_inactive_rules(item: Mapping, rules: list) -> dict:
    """The field of a message without the sentences of its superseded or expired rules."""
    out = _field(item)
    text = out["text"]
    cuts = sorted((r["start"], r["end"]) for r in rules
                  if r.get("status") != "active" and r.get("message", r.get("turn")) == item.get("message", item.get("turn"))
                  and isinstance(r.get("start"), int) and text[r["start"]:r["end"]].strip() == r["text"])
    for start, end in reversed(cuts):
        text = text[:start] + text[end:]
    out["text"] = re.sub(r"[ \t]{2,}", " ", text).strip() if cuts else text
    return out


def text_task(state: Mapping) -> dict:
    """The text task of the record, for the readers of `control["task"]`: the active
    objective, the amendments in turn order, the active restrictions newest first, the
    active permissions, and the earlier objective of an unresolved follow-up.

    The objective and the amendments leave out the sentences of a superseded or expired
    rule, so a classifier never reads an old restriction as current. The record keeps the
    whole message."""
    rules = list(state.get("source_rules") or [])
    task: dict = {"objective": _without_inactive_rules(state.get("objective") or {}, rules)}
    if state.get("amendments"):
        task["amendments"] = [_without_inactive_rules(a, rules) for a in state["amendments"]]
    active = [r for r in rules if r.get("status") == "active"]
    restrictions = [_field(r) for r in reversed(active) if r["effect"] == "restrict"]
    if restrictions:
        task["constraints"] = list({r["text"].casefold(): r for r in reversed(restrictions)}.values())[::-1]
    permissions = [_field(r) for r in reversed(active) if r["effect"] == "allow"]
    if permissions:
        task["allowed_sources"] = permissions
    if state.get("earlier_objective"):
        task["earlier_objective"] = _field(state["earlier_objective"])
    return task


def complete_interpretation(state: Optional[Mapping]) -> bool:
    """Whether the record can support a completion claim: resolved, read from complete
    evidence, and without an omission of objective, amendment or output evidence."""
    state = state or {}
    if state.get("interpretation_state", "resolved") != "resolved":
        return False
    if not (state.get("reconstruction") or {}).get("complete", True):
        return False
    return not any(o.get("field") in ("output_spec", "amendments", "objective")
                   for o in state.get("omissions") or [])


def requirements(state: Optional[Mapping]) -> dict:
    """The output requirement of the record: `file` when an active or uncertain group asks
    for a file, the active `groups`, the `names` and the exact `count` of all active groups,
    and `exact` when every active group has an exact count."""
    spec = (state or {}).get("output_spec") or {}
    groups = [g for g in spec.get("groups") or [] if g.get("status") == "active"]
    names = list(dict.fromkeys(n for g in groups for n in g.get("names") or []))
    exact = all(g.get("count") is not None for g in groups)
    count = sum(int(g.get("count") or 0) for g in groups)
    return {"file": bool(groups or spec.get("uncertain")), "groups": groups, "names": names,
            "count": max(count, len(names)), "exact": exact,
            "delivered_before": [d["name"] for d in spec.get("delivered_before") or []]}


def delivery(state: Optional[Mapping], delivered: Iterable[str]) -> dict:
    """The requested outputs of the record compared with the names of the delivered files.

    `state` is `none` when the task asks for no file, `complete` when every active group has
    its named files and its count of further distinct files, and `incomplete` when one is
    missing. It is `unknown` when a group has no exact count, when the interpretation is
    unresolved, or when its evidence is incomplete. Names and counts state only whether the
    requested files exist. They never state that the content answers the task."""
    required = requirements(state)
    delivered = list(dict.fromkeys(list(required["delivered_before"]) + list(delivered)))
    out = {"requested": required["names"], "requested_count": required["count"],
           "delivered": delivered, "missing": [], "groups": [], "evidence": False}
    complete = complete_interpretation(state)
    if not required["file"]:
        out["state"] = "none" if complete else "unknown"
        return out
    named = set(required["names"])
    out["missing"] = [n for n in required["names"] if n not in delivered]
    unnamed = sum(max(0, int(g.get("count") or 0) - len(g.get("names") or [])) for g in required["groups"])
    others = [n for n in delivered if n not in named]
    for group in required["groups"]:
        out["groups"].append({"id": group.get("id"), "noun": group.get("noun"), "count": group.get("count"),
                              "names": list(group.get("names") or [])})
    if not required["groups"] or not required["exact"] or not complete:
        out["state"] = "unknown"
        return out
    done = not out["missing"] and len(others) >= unnamed
    out["state"], out["evidence"] = ("complete" if done else "incomplete"), done
    if len(others) < unnamed:
        out["missing_unnamed"] = unnamed - len(others)
    return out


def urls(state: Optional[Mapping]) -> list[str]:
    """The web addresses that the objective and the amendments name."""
    state = state or {}
    texts = [str((state.get("objective") or {}).get("text") or "")]
    texts += [str(a.get("text") or "") for a in state.get("amendments") or []]
    return list(dict.fromkeys(u.rstrip(".,;:!?)") for t in texts for u in re.findall(r"https?://\S+", t)))


def reconstruct(records: list[Mapping], complete: bool) -> dict:
    """The record of the earlier turns from their stored evidence, oldest first.

    An item of `records` is `{"state": <stored record>}` for a turn with a versioned record,
    or `{"request", "turn", "task"}` for an older turn. `delivered` lists the files that the
    turn delivered. A stored record is the base, and the later items apply in order. An older
    first item seeds the rules that its recorded text task carried. An item without a request
    changes nothing. `complete` is false when
    the bounded read reached neither the first turn of the session nor a stored record."""
    state: Optional[dict] = None
    found = False
    for position, item in enumerate(records):
        stored = item.get("state")
        if isinstance(stored, Mapping) and stored.get("schema_version") == SCHEMA_VERSION:
            state, found = copy.deepcopy(dict(stored)), True
        elif not str(item.get("request") or "").strip():
            continue
        else:
            task = item.get("task") if isinstance(item.get("task"), Mapping) else {}
            if state is None and position == 0 and _items(task, "constraints"):
                state = empty()
                for rule in _items(task, "constraints"):
                    if rule.get("turn") is None or rule.get("turn") != item.get("turn"):
                        state["source_rules"].extend(source_rules(rule["text"], rule.get("turn"),
                                                                  str(rule.get("source") or "user")))
            state = derive(str(item.get("request") or ""), item.get("turn"), state)
        record_delivery(state, item.get("delivered") or [], item.get("turn"))
    state = state or empty()
    state["reconstruction"] = {"turns_read": len(records), "complete": bool(complete or found),
                               "source": "state" if found else ("records" if records else "none")}
    return state


def from_text_tasks(earlier: Iterable[Mapping]) -> dict:
    """The record of earlier turns given as text tasks or records, oldest first. A text task
    gives its newest amendment, or else its objective, as the message of its turn."""
    records = []
    for task in earlier:
        if isinstance(task, Mapping) and task.get("schema_version") == SCHEMA_VERSION:
            records.append({"state": task})
            continue
        items = _items(task, "amendments") or _items(task, "objective")
        last = items[-1] if items else {"text": ""}
        records.append({"request": last["text"], "turn": last.get("turn"), "task": task})
    return reconstruct(records, complete=True)


__all__ = ["SCHEMA_VERSION", "classify", "complete_interpretation", "delivery", "derive",
           "from_structured", "from_text_tasks", "output_groups", "reconstruct", "record_delivery",
           "requirements", "source_rules", "source_scope", "structured_groups", "text_task", "urls"]
