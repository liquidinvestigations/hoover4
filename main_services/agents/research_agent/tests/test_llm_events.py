"""Unit tests for llm_events helpers."""

from research_agent.llm_events import provider_from_base_url, telemetry_username


def test_telemetry_username_collapses_guests():
    assert telemetry_username(None) == "guest"
    assert telemetry_username("") == "guest"
    assert telemetry_username("guest") == "guest"
    assert telemetry_username("guest-abc123") == "guest"
    assert telemetry_username("ann") == "ann"


def test_provider_from_base_url_derives_label(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER_NAME", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
    assert provider_from_base_url() == "nvidia"


def test_the_row_goes_in_the_body_not_in_the_sql(monkeypatch):
    """A username with a quote in it must not be able to end the INSERT statement.

    `username` arrives from an HTTP header. It used to be interpolated into a `VALUES`
    clause with no quoting at all (session_id, model and provider got a
    `.replace("'", "")`, which is not an escaper either), on a statement running as the
    ClickHouse admin. Everything now travels as JSON in the request body.
    """
    import json

    from research_agent import llm_events

    sent = []

    class FakeResponse:
        status_code = 200
        text = ""

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, params=None, content=None, **kwargs):
            sent.append((params or {}, content))
            return FakeResponse()

    monkeypatch.setenv("CLICKHOUSE_URL", "http://clickhouse:8123")
    monkeypatch.setattr(llm_events.httpx, "Client", lambda *a, **k: FakeClient())

    llm_events.record_llm_call(
        llm_events.LlmCallStats(
            provider="nvidia", model_id="m'; DROP TABLE llm_call_events; --",
            latency_ms=12, prompt_tokens=3,
        ),
        username="o'brien",
        session_id="s'1",
    )

    assert len(sent) == 2
    for params, content in sent:
        query = params["query"]
        assert query.endswith("FORMAT JSONEachRow")
        # The whole point: no value of any kind reaches the statement.
        assert "o'brien" not in query and "DROP TABLE" not in query
        row = json.loads(content.decode("utf-8"))
        assert row["username"] == "o'brien"
    assert sent[0][1] and json.loads(sent[0][1].decode())["model_id"].startswith("m'; DROP")
