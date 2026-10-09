"""The client of the local systemone route and of its raw completion route.

`CHAT_CLASSIFIER_URL` is the base address of the structured server of the selfhosted
provider. `deploy.py` renders it only when that provider is active, so no request goes to a
hosted classifier. The key is the model key of the worker (`summarize._api_key`). An unset
address makes every request `unavailable`, and the run goes on without the answers.

One `Deadline` covers every request of one hook. A request gets the remaining time as its
read timeout, and a request that cannot start before the deadline is `timeout`. Each request
runs in a thread with its own HTTP session, and a cancelled or expired request closes that
session, so the thread ends with the connection.

`ask` sends at most `MAX_QUESTIONS` questions in one request and splits a larger set into
chunks in the given order. Each answer is validated against the type of its question. A
missing or malformed answer is left out and counted, never turned into a score of zero.
Scores keep their full precision.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Callable, Dict, Mapping, Optional

import requests

from tasks.P_agent.control.model import ClassifierResult, freeze

log = logging.getLogger(__name__)

CLASSIFIER_URL_ENV = "CHAT_CLASSIFIER_URL"
SYSTEMONE_PATH = "/v1/systemone"
RAW_PATH = "/v1/raw/chat/completions"
#: The most questions that the server accepts in one request.
MAX_QUESTIONS = 64
CONNECT_SECONDS = 3.0


class Deadline:
    """The end of one hook's time, on a clock that tests can replace."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic,
                 cancelled: Callable[[], bool] = lambda: False):
        self._clock = clock
        self._end = clock() + max(0.0, seconds)
        self.cancelled = cancelled

    def remaining(self) -> float:
        return max(0.0, self._end - self._clock())


def _valid(question: Mapping[str, Any], answer: Any) -> bool:
    if not isinstance(answer, Mapping):
        return False
    kind = question.get("type")
    if kind == "noul":
        value = answer.get("noul")
        return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= value <= 1.0
    if kind == "choice":
        options = set((question.get("criteria") or {}).keys())
        probs = answer.get("probabilities")
        return (answer.get("choice") in options and isinstance(probs, Mapping)
                and all(isinstance(v, (int, float)) for v in probs.values()))
    if kind == "score":
        return isinstance(answer.get("score"), (int, float)) or isinstance(answer.get("level"), str)
    if kind == "span":
        return isinstance(answer.get("text"), str) or answer.get("text") is None
    if kind == "spans":
        items = answer.get("items")
        return isinstance(items, list) and all(isinstance(i, Mapping) and isinstance(i.get("text"), str)
                                               for i in items)
    return False


class Classifier:
    """The requests of one hook, under one deadline."""

    def __init__(self, deadline: Deadline, base_url: Optional[str] = None,
                 api_key: Optional[str] = None, model: Optional[str] = None,
                 post: Optional[Callable[..., Any]] = None):
        self.deadline = deadline
        self.base_url = (base_url if base_url is not None
                         else os.environ.get(CLASSIFIER_URL_ENV, "")).strip().rstrip("/")
        if api_key is None:
            from tasks.P_agent.summarize import _api_key
            api_key = _api_key() if self.base_url else ""
        self.api_key = api_key
        self.model = model if model is not None else (os.environ.get("LLM_MODEL") or "").strip()
        self._post = post or _post_json
        self.log: list[dict] = []
        self.events: list[dict] = []
        self._request_seq = 0

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def _request(self, path: str, body: dict) -> tuple[str, Any, int, str]:
        """(status, response JSON, duration ms, error) of one POST."""
        remaining = self.deadline.remaining()
        if not self.available:
            return "unavailable", None, 0, "no local classifier route is configured"
        if remaining <= 0.05:
            return "timeout", None, 0, "the hook deadline passed before the request"
        if self.deadline.cancelled():
            raise asyncio.CancelledError()
        session = requests.Session()
        started = time.monotonic()
        try:
            task = asyncio.ensure_future(asyncio.to_thread(
                self._post, session, self.base_url + path, body, self.api_key,
                (min(CONNECT_SECONDS, remaining), remaining)))
            while True:
                done, _ = await asyncio.wait({task}, timeout=min(0.5, self.deadline.remaining() + 0.01))
                if done:
                    break
                if self.deadline.cancelled():
                    session.close()
                    raise asyncio.CancelledError()
                if self.deadline.remaining() <= 0:
                    session.close()
                    return "timeout", None, int((time.monotonic() - started) * 1000), "deadline"
            status_code, payload, error = task.result()
        except asyncio.CancelledError:
            session.close()
            raise
        # The error records the exception type only. Its message names the server address,
        # and the error text is stored in the decision of the event.
        except requests.Timeout as exc:
            return "timeout", None, int((time.monotonic() - started) * 1000), type(exc).__name__
        except requests.ConnectionError as exc:
            return "unavailable", None, int((time.monotonic() - started) * 1000), type(exc).__name__
        finally:
            session.close()
        ms = int((time.monotonic() - started) * 1000)
        if error:
            return "unavailable", None, ms, error
        if status_code != 200:
            return "http_error", payload, ms, f"HTTP {status_code}"
        return "ok", payload, ms, ""

    async def ask(self, state: Mapping[str, Any], questions: Mapping[str, Any],
                  instructions: str = "", trace: Optional[dict] = None) -> ClassifierResult:
        if not questions:
            return ClassifierResult(status="skipped")
        ids = list(questions)
        chunks = [ids[i:i + MAX_QUESTIONS] for i in range(0, len(ids), MAX_QUESTIONS)]

        async def one(chunk):
            self._request_seq += 1
            seq = self._request_seq
            budget = int(self.deadline.remaining() * 1000)
            body = {"model": self.model, "state": json.loads(json.dumps(state, default=str)),
                    "questions": {q: json.loads(json.dumps(questions[q])) for q in chunk}}
            if instructions:
                body["instructions"] = instructions
            started = time.monotonic()
            try:
                status, payload, ms, error = await self._request(SYSTEMONE_PATH, body)
            except asyncio.CancelledError:
                elapsed = int((time.monotonic() - started) * 1000)
                self.events.append(self._event(seq, chunk, questions, "cancelled", None, elapsed, budget, "", trace))
                raise
            got = payload.get("answers") if isinstance(payload, Mapping) else None
            malformed = status == "ok" and (not isinstance(got, Mapping) or
                        any(q not in got or not _valid(questions[q], got[q]) for q in chunk) or
                        bool(set(got) - set(chunk)))
            outcome = "malformed" if malformed else status
            event = self._event(seq, chunk, questions, outcome, payload, ms, budget, error, trace)
            self.events.append(event)
            return status, payload, ms, error

        results = await asyncio.gather(*(one(c) for c in chunks))
        answers: Dict[str, Any] = {}
        statuses = []
        malformed = 0
        duration = 0
        errors = []
        model = ""
        for chunk, (status, payload, ms, error) in zip(chunks, results):
            duration = max(duration, ms)
            if error:
                errors.append(error)
            if status == "ok":
                got = payload.get("answers") if isinstance(payload, Mapping) else None
                if not isinstance(got, Mapping):
                    status = "malformed"
                else:
                    model = str(payload.get("model") or model)
                    for qid in chunk:
                        if qid in got and _valid(questions[qid], got[qid]):
                            answers[qid] = got[qid]
                        else:
                            malformed += 1
                    unknown = set(got) - set(chunk)
                    malformed += len(unknown)
            statuses.append(status)
        status = next((s for s in statuses if s != "ok"), "ok")
        if status == "ok" and malformed and not answers:
            status = "malformed"
        record = {"kind": "systemone", "status": status, "asked": len(ids),
                  "answered": len(answers), "malformed": malformed, "duration_ms": duration,
                  "chunks": len(chunks), "model": model or self.model, "error": "; ".join(errors)[:300]}
        self.log.append(record)
        return ClassifierResult(status=status, answers=freeze(answers), model=model or self.model,
                                duration_ms=duration, error=record["error"], asked=len(ids))

    async def complete(self, prompt: str, max_tokens: int = 300, trace: Optional[dict] = None) -> ClassifierResult:
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                "max_tokens": int(max_tokens),
                "chat_template_kwargs": {"enable_thinking": False}}
        self._request_seq += 1
        seq = self._request_seq
        budget = int(self.deadline.remaining() * 1000)
        started = time.monotonic()
        try:
            status, payload, ms, error = await self._request(RAW_PATH, body)
        except asyncio.CancelledError:
            elapsed = int((time.monotonic() - started) * 1000)
            event = self._event(seq, [], {}, "cancelled", None, elapsed, budget, "", trace)
            event["route"] = "completion"
            self.events.append(event)
            raise
        text = ""
        if status == "ok":
            try:
                text = str(payload["choices"][0]["message"]["content"] or "")
            except (KeyError, IndexError, TypeError):
                status = "malformed"
        event = self._event(seq, [], {}, status, payload, ms, budget, error, trace)
        event["route"] = "completion"
        self.events.append(event)
        self.log.append({"kind": "completion", "status": status, "duration_ms": ms,
                         "model": self.model, "error": error[:300]})
        return ClassifierResult(status=status, text=text, model=self.model, duration_ms=ms,
                                error=error[:300])


    def _event(self, seq, ids, questions, status, payload, ms, budget, error, trace):
        got = payload.get("answers", {}) if isinstance(payload, Mapping) else {}
        got = got if isinstance(got, Mapping) else {}
        states, values = [], []
        for qid in ids:
            valid = qid in got and _valid(questions[qid], got[qid])
            states.append("ok" if valid else "malformed" if qid in got else "missing")
            answer = got.get(qid) if valid else {}
            value = answer.get("noul", answer.get("score")) if isinstance(answer, Mapping) else None
            values.append(float(value) if isinstance(value, (int, float)) else None)
        return {"event_time": int(time.time() * 1000), "sequence": seq,
                **(trace or {}), "model_id": str(payload.get("model") or self.model) if isinstance(payload, Mapping) else self.model,
                "route": "systemone", "question_ids": list(ids),
                "question_types": [questions[q]["type"] for q in ids],
                "answer_values": values, "answer_status": states, "outcome": status,
                "http_status": int(error[5:]) if error.startswith("HTTP ") else 200 if status in ("ok", "malformed") else 0,
                "latency_ms": ms, "deadline_ms": budget}


def write_events(row, decision):
    """Insert one hook's request samples. Telemetry failure never fails the turn."""
    from datetime import datetime, timezone
    from database.clickhouse import get_global_client

    events = decision.get("classifier_events") or []
    if not events:
        return
    columns = ["event_time", "username", "session_id", "run_id", "turn_seq", "hook",
               "rule_id", "handler", "definition_revision", "request_id", "model_id", "route",
               "question_ids", "question_types", "answer_values", "answer_status", "outcome",
               "http_status", "latency_ms", "deadline_ms", "actions", "positive_answers", "scored_answers"]
    records, traffic = [], []
    for event in events:
        ended = datetime.fromtimestamp(event["event_time"] / 1000, timezone.utc)
        item = {**event, "event_time": ended, "username": row.username or "guest",
                "session_id": row.session_id, "run_id": str(row.run_id), "turn_seq": row.turn_seq,
                "hook": decision["event"]["hook"], "definition_revision": decision["definition_revision"],
                "request_id": decision["event"]["id"] + ":" + str(event["sequence"])}
        records.append([item.get(c, "") for c in columns])
        traffic.append([ended, "systemone", "selfhosted", row.username or "guest", row.session_id,
                        event["latency_ms"], int(event["outcome"] == "ok"), event["model_id"]])
    try:
        with get_global_client() as client:
            settings = {"async_insert": 1, "wait_for_async_insert": 1}
            client.insert("systemone_call_events", records, column_names=columns, settings=settings)
            client.insert("ai_service_telemetry", traffic,
                          column_names=["event_time", "service", "provider", "username", "session_id", "latency_ms", "ok", "detail"],
                          settings=settings)
    except Exception as exc:
        log.warning("systemone telemetry was not stored: %s", type(exc).__name__)


def _post_json(session: requests.Session, url: str, body: dict, key: str,
               timeout: tuple[float, float]) -> tuple[int, Any, str]:
    """(HTTP status, JSON body or None, connection error text). Never logs the key."""
    try:
        response = session.post(url, json=body, timeout=timeout,
                                headers={"Authorization": f"Bearer {key}"})
    except (requests.Timeout, requests.ConnectionError):
        raise
    except requests.RequestException as exc:
        return 0, None, type(exc).__name__
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload, ""
