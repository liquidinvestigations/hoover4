"""Report the detected language of the stored answers, follow-up suggestions and titles of
chat sessions, with the fastText model `lid.176.ftz` that the pipeline uses.

Usage, from the repository root, with the session ids from the `session_url` of each
`conversation.json` that `website/observe-chat.sh` wrote:

    docker exec -i hoover4-worker sh -lc 'cd /app && uv run python - --expected de SESSION_ID ...' \\
        < scripts/i18n/check_answer_language.py

The script prints one JSON object for each text: the session, the kind (`answer`,
`follow_up` or `title`), the detected language, its score, and `match`. Before detection,
it removes code, links, citation handles and quoted text, because an answer quotes its
sources in their own language. A text with fewer than 40 letters after that has the
language `und`. Language detection is one signal of the answer language. It does not
measure the quality of the answer or of its research.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from database.clickhouse import get_global_client
from tasks.document_language import language_model

#: fastText labels that name a supported code differently.
LABELS = {"no": "nb", "nn": "nb", "iw": "he"}

_REMOVED = [
    re.compile(r"```.*?```", re.S),
    re.compile(r"`[^`]*`"),
    re.compile(r"\[([^\]]*)\]\([^)]*\)"),
    re.compile(r"https?://\S+"),
    re.compile(r"\[[A-Z]\d+\]"),
    re.compile(r"“[^”]*”|\"[^\"\n]*\"|„[^“”]*[“”]|«[^»]*»"),
]


def plain(text: str) -> str:
    for pattern in _REMOVED:
        text = pattern.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def detect(text: str) -> tuple[str, float]:
    sample = plain(text)[:4000]
    if sum(c.isalpha() for c in sample) < 40:
        return "und", 0.0
    labels, scores = language_model().predict(sample, k=1)
    label = labels[0].removeprefix("__label__")
    return LABELS.get(label, label), round(float(scores[0]), 3)


def texts(session_id: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    with get_global_client() as client:
        rows = client.query(
            "SELECT content, usage_json FROM chat_messages FINAL WHERE session_id = {s:String} "
            "AND role = 'assistant' ORDER BY seq", parameters={"s": session_id}).result_rows
        titles = client.query(
            "SELECT title FROM chat_sessions FINAL WHERE session_id = {s:String}",
            parameters={"s": session_id}).result_rows
    for content, usage_json in rows:
        if content and content.strip():
            out.append(("answer", content))
        try:
            usage = json.loads(usage_json or "{}")
        except ValueError:
            usage = {}
        for prompt in usage.get("follow_up_prompts") or []:
            out.append(("follow_up", str(prompt)))
    for (title,) in titles:
        out.append(("title", title))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--expected", required=True, help="the expected language code")
    parser.add_argument("sessions", nargs="+")
    args = parser.parse_args()
    for session_id in args.sessions:
        for kind, text in texts(session_id):
            language, score = detect(text)
            print(json.dumps({"session": session_id, "kind": kind, "language": language,
                              "score": score, "match": language == args.expected,
                              "chars": len(text)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
