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
LABEL_PATTERN = re.compile(r"\[([DW]\d+)\]")
WORD_PATTERN = re.compile(r"[a-z0-9]{3,}")
STOP_WORDS = {"the", "and", "for", "with", "from", "that", "this", "what", "which", "their",
              "emails", "email", "documents", "document", "find", "search", "identify", "any",
              "about", "between", "into", "who", "when", "where", "how", "are", "was", "were"}

#: Word-set overlap at or above which a proposed intent repeats an existing one.
DUPLICATE_OVERLAP = 0.8


def extract_json_object(text: str) -> dict:
    """The JSON object of a reply, from a fence or the outermost braces."""
    text = THINK_PATTERN.sub("", text or "").strip()
    fenced = FENCE_PATTERN.findall(text)
    if fenced:
        text = fenced[-1]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("the reply holds no JSON object")
    value = json.loads(text[start:end + 1])
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
                 not_found_ids: set | None = None, goal_texts: dict | None = None) -> dict:
    """The `reason_result` payload of one reply.

    `valid_ids` are the live fact ids, `sourced_ids` the live sourced ones, `earlier` the
    objectives of every intent the board has, `idle` whether no intent is open or running,
    `goal_ids` the goal fact ids, `not_found_ids` the live not-found facts, and `goal_texts`
    the goal id of each goal text. A review that names a goal by its exact text names that
    goal.

    A review names each goal with the facts that answer it and a statement. A goal's facts
    are sourced or not-found facts, and the review as a whole needs one sourced fact. A
    review that leaves out a goal, or names another fact, is no review.
    """
    goal_ids = list(goal_ids or [m.FIRST_GOAL_ID])
    answerable = set(sourced_ids) | set(not_found_ids or ())
    payload = {"raw": (text or "")[:6000], "problems": []}
    try:
        data = extract_json_object(text)
    except (ValueError, json.JSONDecodeError) as exc:
        payload.update(outcome="invalid", error=str(exc))
        return payload
    if "review" in data or "complete" in data:
        goals, problems = [], []
        for entry in _review_goals(data.get("review") or data.get("complete") or {}, goal_ids):
            if not isinstance(entry, dict):
                problems.append("a review goal is not an object")
                continue
            goal = str(entry.get("goal") or "")
            goal = (goal_texts or {}).get(goal.strip(), goal)
            from_ids = [str(f) for f in entry.get("from") or []]
            if goal not in goal_ids:
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
    """The last fenced JSON block of an answer, or None."""
    blocks = FENCE_PATTERN.findall(THINK_PATTERN.sub("", answer or ""))
    for block in reversed(blocks):
        try:
            value = json.loads(block)
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
