"""Checks of the model output of a reason call and of an explore answer.

The reason reply must be one JSON object. A reply inside a Markdown fence is accepted,
because the chat model sometimes adds one. Every check here records what it changed, so a
dropped intent or a downgraded fact is visible in the board events.
"""

import json
import re

from tasks.P_board import model as m

THINK_PATTERN = re.compile(r"<think>.*?</think>", re.S)
FENCE_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
#: A fenced body that does not start with a brace: the model left out the opening brace.
OPEN_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(\"[^`]*?)\s*```", re.S)
#: A tool call that the model wrote as text, `[submit_board_fact]{...}`, in place of a call.
TEXT_CALL_PATTERN = re.compile(r"\[(?:%s)\]\s*(?=\{)" % re.escape(m.SUBMIT_FACT_TOOL))
LABEL_PATTERN = re.compile(r"\[([DW]\d+)\]")
#: A comma before a closing bracket, which JSON does not allow and the model sometimes writes.
TRAILING_COMMA = re.compile(r",(\s*[}\]])")
WORD_PATTERN = re.compile(r"[a-z0-9]{3,}")
STOP_WORDS = {"the", "and", "for", "with", "from", "that", "this", "what", "which", "their",
              "emails", "email", "documents", "document", "find", "search", "identify", "any",
              "about", "between", "into", "who", "when", "where", "how", "are", "was", "were"}

#: Word-set overlap at or above which a proposed intent repeats an existing one.
DUPLICATE_OVERLAP = 0.8


def extract_json_object(text: str) -> dict:
    """The JSON object of a reply, from a fence or the outermost braces. A fenced body that
    starts with a key, because the model left out the opening brace, gets that brace."""
    text = THINK_PATTERN.sub("", text or "").strip()
    fenced = FENCE_PATTERN.findall(text)
    keyed = OPEN_FENCE_PATTERN.findall(text)
    if fenced:
        text = fenced[-1]
    elif keyed:
        body = keyed[-1].strip()
        text = "{" + body + ("" if body.endswith("}") else "}")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("the reply holds no JSON object")
    candidate = text[start:end + 1]
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        value = json.loads(TRAILING_COMMA.sub(r"\1", candidate))
    if not isinstance(value, dict):
        raise ValueError("the reply is not a JSON object")
    return value


def _stem(word: str) -> str:
    """A crude stem, so that "mention" and "mentioning" count as one word."""
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _words(text: str) -> set[str]:
    return {_stem(w) for w in WORD_PATTERN.findall((text or "").lower()) if w not in STOP_WORDS}


def is_duplicate(objective: str, earlier: str) -> bool:
    """Whether two objectives name the same work: the overlap of their word sets, measured
    against the smaller set, is at or above `DUPLICATE_OVERLAP`."""
    a, b = _words(objective), _words(earlier)
    if not a or not b:
        return False
    return len(a & b) / min(len(a), len(b)) >= DUPLICATE_OVERLAP


def _review_goals(review, goal_ids: list[str]) -> list:
    """The goal entries of a review object. A review without `goals` answers the first goal
    with its own `from` and `statement`."""
    if not isinstance(review, dict):
        return []
    goals = review.get("goals")
    if isinstance(goals, list):
        return goals
    return [{"goal": goal_ids[0] if goal_ids else m.FIRST_GOAL_ID, "from": review.get("from"),
             "statement": review.get("statement") or review.get("description")}]


def parse_reason(text: str, valid_ids: set, sourced_ids: set, earlier: list[str],
                 idle: bool, goal_ids: list[str] | None = None,
                 not_found_ids: set | None = None, goal_texts: dict | None = None,
                 closed_ids: set | None = None) -> dict:
    """The `reason_result` payload of one reply.

    `valid_ids` are the live fact ids, `sourced_ids` the live sourced ones, `earlier` the
    objectives of every intent the board has, `idle` whether no intent is open or running,
    `goal_ids` the goal fact ids, `not_found_ids` the live not-found facts, and `goal_texts`
    the goal id of each goal text. A review that names a goal by its exact text names that
    goal.

    A review names each goal with the facts that answer it and a statement. A goal's facts
    are sourced or not-found facts, and the review as a whole needs one sourced fact. A
    review that leaves out a goal, or names another fact, is no review. An entry for a goal
    of `closed_ids` (accepted already) is dropped with a note and does not refuse the review.
    An id of `from` that is no fact, such as a correction, is dropped with a note when the
    entry names other facts.
    A top-level `goals` list without `review` is read as a review.
    """
    goal_ids = list(goal_ids or [m.FIRST_GOAL_ID])
    answerable = set(sourced_ids) | set(not_found_ids or ())
    payload = {"raw": (text or "")[:6000], "problems": []}
    try:
        data = extract_json_object(text)
    except (ValueError, json.JSONDecodeError) as exc:
        payload.update(outcome="invalid", error=str(exc))
        return payload
    if "goals" in data and not any(k in data for k in ("review", "complete", "intents")):
        data = {"review": {"goals": data["goals"]}}
    if "review" in data or "complete" in data:
        goals, problems, skipped, dropped = [], [], [], []
        for entry in _review_goals(data.get("review") or data.get("complete") or {}, goal_ids):
            if not isinstance(entry, dict):
                problems.append("a review goal is not an object")
                continue
            goal = str(entry.get("goal") or "")
            goal = (goal_texts or {}).get(goal.strip(), goal)
            from_ids = [str(f) for f in entry.get("from") or []]
            stray = [f for f in from_ids if f not in valid_ids and f not in answerable]
            if stray and len(stray) < len(from_ids):
                from_ids = [f for f in from_ids if f not in stray]
                dropped.append(f"dropped {stray} from the answer of {goal}: not a fact")
            if goal in (closed_ids or ()):
                skipped.append(goal)
            elif goal not in goal_ids:
                problems.append(f"review names the unknown goal {goal!r}")
            elif not from_ids or not set(from_ids) <= answerable:
                problems.append(f"review of {goal} from {from_ids} names a fact that is not sourced")
            elif goal not in {g["goal"] for g in goals}:
                goals.append({"goal": goal, "from": from_ids,
                              "statement": str(entry.get("statement") or "")})
        missing = [g for g in goal_ids if g not in {x["goal"] for x in goals}]
        if missing and not problems:
            problems.append("review leaves out the goals " + ", ".join(missing))
        used = [f for g in goals for f in g["from"]]
        if not problems and not set(used) & set(sourced_ids):
            problems.append("review names no sourced fact")
        if not problems:
            payload.update(outcome="review", review={
                "from": list(dict.fromkeys(used)), "goals": goals,
                "statement": "\n\n".join(g["statement"] for g in goals if g["statement"])})
            payload["problems"].extend(f"dropped the answer of the accepted goal {g}" for g in skipped)
            payload["problems"].extend(dropped)
            return payload
        payload["problems"].extend(problems)
    items = data.get("intents")
    if items is None and isinstance(data.get("intent"), dict):
        items = [data["intent"]]
    kept = []
    seen = list(earlier)
    for item in items or []:
        if not isinstance(item, dict):
            payload["problems"].append("an intent is not an object")
            continue
        objective = str(item.get("objective") or item.get("description") or "").strip()
        from_ids = [str(f) for f in item.get("from") or []]
        if not objective or not from_ids:
            payload["problems"].append("an intent lacks an objective or its from list")
            continue
        if not set(from_ids) <= valid_ids:
            payload["problems"].append(f"intent from {from_ids} names an unknown or rejected fact")
            continue
        if any(is_duplicate(objective, other) for other in seen):
            payload["problems"].append(f"dropped as a repeat: {objective[:160]}")
            continue
        seen.append(objective)
        kept.append({"from": from_ids, "objective": objective,
                     "brief": str(item.get("brief") or "").strip()})
        if len(kept) >= m.MAX_INTENTS:
            break
    if kept:
        payload.update(outcome="intents", intents=kept)
    else:
        payload.update(outcome="noop", idle=idle)
    return payload


def parse_explore_block(answer: str) -> dict | None:
    """The last fenced JSON block of an answer, else the arguments of a
    `[submit_board_fact]{...}` call that the model wrote as text, or None."""
    answer = THINK_PATTERN.sub("", answer or "")
    blocks = FENCE_PATTERN.findall(answer)
    for block in reversed(blocks):
        try:
            value = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    for match in reversed(list(TEXT_CALL_PATTERN.finditer(answer))):
        try:
            value, _ = json.JSONDecoder().raw_decode(answer, match.end())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def labels_of(text: str, listed) -> list[str]:
    """The labels a fact names, in its text or in its citations list."""
    labels = set(LABEL_PATTERN.findall(text or ""))
    for item in listed or []:
        label = str(item).strip().strip("[]")
        if re.fullmatch(r"[DW]\d+", label):
            labels.add(label)
    return sorted(labels, key=lambda x: (x[0], int(x[1:])))


#: Limits of the checks of a generated label. The prompt asks for 3 to 4 title words, 15 to
#: 20 summary words for a node and 10 to 15 for a board. The checks cut a longer text.
SLUG_WORDS = 4
SLUG_CHARS = 40
TITLE_WORDS = 5
SUMMARY_WORDS = 24
BOARD_SUMMARY_WORDS = 20

SLUG_WORD_PATTERN = re.compile(r"[a-z0-9]+")
#: Words of a slug that name a node type. The kind prefix of the slug gives the type.
TYPE_WORDS = {"intent", "fact", "correction", "origin", "goal"}


def slug_words(text: str, limit: int = SLUG_WORDS) -> list[str]:
    """The lowercase letter and digit runs of a text, at most `limit`, within `SLUG_CHARS`."""
    words: list[str] = []
    for word in SLUG_WORD_PATTERN.findall((text or "").lower()):
        if len(words) >= limit or len("-".join(words + [word])) > SLUG_CHARS:
            break
        words.append(word)
    return words


def cut_words(text: str, limit: int) -> str:
    """The text with collapsed whitespace, cut after `limit` words without an ellipsis."""
    return " ".join(str(text or "").split()[:limit])


def parse_labels(text: str, sources: dict) -> dict:
    """The checked labels of one reply, by node id: `{"slug", "title", "summary"}`.

    `sources` maps each node id that the call asked for to the text that a fallback reads.
    An entry for another id is dropped. An entry without a title or a summary is dropped, so
    its node counts a failed attempt. A slug that is empty after the clean-up comes from the
    first 3 words of the title, then from the first 3 words of the source text. A reply
    without a JSON object gives no label.
    """
    try:
        data = extract_json_object(text)
    except (ValueError, json.JSONDecodeError):
        return {}
    entries = data.get("labels")
    out = {}
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        node_id = str(entry.get("id") or "").strip()
        if node_id not in sources or node_id in out:
            continue
        title = cut_words(entry.get("title"), TITLE_WORDS)
        summary = cut_words(entry.get("summary"), SUMMARY_WORDS)
        if not title or not summary:
            continue
        words = [w for w in slug_words(str(entry.get("slug") or "").replace("-", " "), SLUG_WORDS + 1)
                 if w not in TYPE_WORDS][:SLUG_WORDS]
        words = words or slug_words(title, 3) or slug_words(sources[node_id], 3)
        if not words:
            continue
        out[node_id] = {"slug": "-".join(words), "title": title, "summary": summary}
    return out


def parse_board_summary(text: str) -> str:
    """The board summary of one reply: the first line with words, reasoning blocks and a label
    removed, cut at `BOARD_SUMMARY_WORDS` words. Empty when the reply has no words."""
    from tasks.P_agent.summarize import strip_label

    for line in THINK_PATTERN.sub("", text or "").splitlines():
        line = strip_label(line).strip().strip('"')
        if SLUG_WORD_PATTERN.search(line.lower()):
            return cut_words(line, BOARD_SUMMARY_WORDS)
    return ""
