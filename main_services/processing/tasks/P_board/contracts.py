"""Checks of the model output of a reason call and of an explore answer.

The reason reply must be one JSON object. A reply inside a Markdown fence is accepted,
because the chat model sometimes adds one. Every check here records what it changed, so a
dropped intent or a downgraded fact is visible in the board events.
"""

import json
import re

from tasks.llm_json import THINK_PATTERN, extract_json
from tasks.P_board import model as m

FENCE_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
#: A tool call that the model wrote as text, `[submit_board_fact]{...}`, in place of a call.
TEXT_CALL_PATTERN = re.compile(r"\[(?:%s)\]\s*(?=\{)" % re.escape(m.SUBMIT_FACT_TOOL))
LABEL_PATTERN = re.compile(r"\[([DW]\d+)\]")
WORD_PATTERN = re.compile(r"[a-z0-9]{3,}")
STOP_WORDS = {"the", "and", "for", "with", "from", "that", "this", "what", "which", "their",
              "emails", "email", "documents", "document", "find", "search", "identify", "any",
              "about", "between", "into", "who", "when", "where", "how", "are", "was", "were"}

#: Word-set overlap at or above which a proposed intent repeats an existing one.
DUPLICATE_OVERLAP = 0.8


def extract_json_object(text: str) -> dict:
    """The JSON object of a reply, from a fence or the outermost braces. A fenced body that
    starts with a key, because the model left out the opening brace, gets that brace
    (`tasks.llm_json.extract_json`)."""
    return extract_json(text, "object")


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


def _answer_entries(data: dict, goal_ids: list[str]) -> list | None:
    """The goal answers of a reply, or None when it has none. The reply names them as
    `answers`, as `review.goals`, as `complete.goals` or as a top-level `goals`. A review
    object without `goals` answers the first goal with its own `from` and `statement`."""
    if isinstance(data.get("answers"), list):
        return data["answers"]
    if "goals" in data and not any(k in data for k in ("review", "complete")):
        return data["goals"] if isinstance(data["goals"], list) else []
    review = data.get("review") if "review" in data else data.get("complete")
    if review is None:
        return None
    if not isinstance(review, dict):
        return []
    if isinstance(review.get("goals"), list):
        return review["goals"]
    return [{"goal": goal_ids[0] if goal_ids else m.FIRST_GOAL_ID, "from": review.get("from"),
             "statement": review.get("statement") or review.get("description")}]


def _parse_answers(entries: list, valid_ids: set, sourced_ids: set, not_found_ids: set,
                   goal_ids: list[str], goal_texts: dict, closed_ids: set, problems: list) -> list[dict]:
    """The checked goal answers of a reply. See `parse_reason`."""
    answers = []
    for entry in entries:
        if not isinstance(entry, dict):
            problems.append("an answer is not an object")
            continue
        goal = str(entry.get("goal") or "")
        goal = goal_texts.get(goal.strip(), goal)
        from_ids = list(dict.fromkeys(str(f) for f in entry.get("from") or []))
        answerable = sourced_ids | not_found_ids
        if set(from_ids) & answerable:
            stray = [f for f in from_ids if f not in valid_ids and f not in answerable]
            other = [f for f in from_ids if f in valid_ids and f not in answerable]
            if stray:
                problems.append(f"dropped {stray} from the answer of {goal}: not a fact")
            if other:
                problems.append(f"dropped {other} from the answer of {goal}: only sourced and "
                                "not_found facts support an answer")
            from_ids = [f for f in from_ids if f in answerable]
        if goal in closed_ids:
            problems.append(f"dropped the answer of the accepted goal {goal}")
        elif goal not in goal_ids:
            problems.append(f"an answer names the unknown goal {goal!r}")
        elif not from_ids:
            problems.append(f"the answer of {goal} names no fact")
        elif not set(from_ids) <= answerable:
            problems.append(f"the answer of {goal} from {from_ids} names no sourced or not_found fact")
        elif goal in {a["goal"] for a in answers}:
            problems.append(f"dropped a second answer of {goal}")
        else:
            statement = str(entry.get("statement") or "").strip()
            if set(from_ids) & sourced_ids:
                answers.append({"goal": goal, "from": from_ids, "statement": statement,
                                "answer_kind": m.SUPPORTED, "commentary": ""})
            else:
                # Only not-found facts: the records do not establish an answer. The model's
                # text stays as commentary and never becomes the statement.
                answers.append({"goal": goal, "from": from_ids, "statement": m.NOT_ESTABLISHED_STATEMENT,
                                "answer_kind": m.NOT_ESTABLISHED, "commentary": statement[:2000]})
    return answers


def parse_reason(text: str, valid_ids: set, sourced_ids: set, earlier: list[str],
                 idle: bool, goal_ids: list[str] | None = None,
                 not_found_ids: set | None = None, goal_texts: dict | None = None,
                 closed_ids: set | None = None, question_keys: set | None = None,
                 final: bool = False) -> dict:
    """The `reason_result` payload of one reply.

    `valid_ids` are the live fact ids, `sourced_ids` the live sourced ones, `earlier` the
    objectives of every intent the board has, `idle` whether no intent is open or running,
    `goal_ids` the goal fact ids, `not_found_ids` the live not-found facts, `goal_texts` the
    goal id of each goal text, `closed_ids` the goals with an accepted answer, and
    `question_keys` the question keys that the prompt listed.

    A reply can hold answers for some goals and intents for the others. An answer names its
    goal, the facts it rests on and a statement. An answer that names a sourced fact is
    `supported`. An answer that names only not-found facts is `not_established`: its statement
    is the fixed `NOT_ESTABLISHED_STATEMENT`, and the model's text is its commentary. An
    answer is dropped with a note when it names no sourced or not-found fact, an unknown goal
    or an accepted goal. When it names one, the other ids of `from` (an inferred fact, the
    background, a correction or an id that is no fact) are dropped with a note, and the
    answer stays.

    An intent keeps its position in the reply (`position`, from 1), so a dropped intent does
    not renumber the others. Its `slug` is a candidate name. Its `questions` keep only keys
    that the prompt listed. A final reply proposes answers only, and its intents are dropped.

    The outcome is `review` when the answers cover every goal of `goal_ids` without an
    accepted answer and the reply has no intent, `partial` for other answers, `intents` for
    intents only, `noop` for a valid reply without either, and `invalid` for a reply without
    a JSON object.
    """
    goal_ids = list(goal_ids or [m.FIRST_GOAL_ID])
    closed = set(closed_ids or ())
    payload = {"raw": (text or "")[:6000], "problems": []}
    try:
        data = extract_json_object(text)
    except (ValueError, json.JSONDecodeError) as exc:
        payload.update(outcome="invalid", error=str(exc))
        return payload
    problems = payload["problems"]
    entries = _answer_entries(data, goal_ids)
    answers = _parse_answers(entries or [], set(valid_ids), set(sourced_ids), set(not_found_ids or ()),
                             goal_ids, goal_texts or {}, closed, problems)
    items = data.get("intents")
    if items is None and isinstance(data.get("intent"), dict):
        items = [data["intent"]]
    kept = []
    seen = list(earlier)
    allowed = set(question_keys or ())
    if final and items:
        problems.append(f"a final assessment starts no explore: dropped {len(items)} intents")
        items = []
    for position, item in enumerate(items or [], start=1):
        if not isinstance(item, dict):
            problems.append("an intent is not an object")
            continue
        objective = str(item.get("objective") or item.get("description") or "").strip()
        from_ids = [str(f) for f in item.get("from") or []]
        if not objective or not from_ids:
            problems.append("an intent lacks an objective or its from list")
            continue
        if not set(from_ids) <= valid_ids:
            problems.append(f"intent from {from_ids} names an unknown or rejected fact")
            continue
        if any(is_duplicate(objective, other) for other in seen):
            problems.append(f"dropped as a repeat: {objective[:160]}")
            continue
        named = list(dict.fromkeys(str(k) for k in item.get("questions") or []))
        stray = [k for k in named if k not in allowed]
        if stray:
            problems.append(f"discarded question keys {stray}: not listed in the prompt")
        seen.append(objective)
        kept.append({"from": from_ids, "objective": objective,
                     "brief": str(item.get("brief") or "").strip(), "position": position,
                     "slug": str(item.get("slug") or "").strip()[:80],
                     "questions": [k for k in named if k in allowed]})
        if len(kept) >= m.MAX_INTENTS:
            break
    open_goals = [g for g in goal_ids if g not in closed]
    covered = bool(open_goals) and set(open_goals) <= {a["goal"] for a in answers}
    if answers:
        payload["proposals"] = answers
    if kept:
        payload["intents"] = kept
    if answers and covered and not kept:
        payload["outcome"] = "review"
    elif answers:
        payload["outcome"] = "partial"
    elif kept:
        payload["outcome"] = "intents"
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
TYPE_WORDS = {"intent", "fact", "correction", "origin", "goal", "background"}


def slug_words(text: str, limit: int = SLUG_WORDS) -> list[str]:
    """The lowercase letter and digit runs of a text, at most `limit`, within `SLUG_CHARS`.
    Accents and other marks are removed first, so `Ștefan` gives `stefan`."""
    import unicodedata

    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    words: list[str] = []
    for word in SLUG_WORD_PATTERN.findall(plain.lower()):
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
