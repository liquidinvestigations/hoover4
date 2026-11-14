"""The GPU key check (gpu_key.py): the start refuses an empty key, and every route except
/health needs the key. The test needs FastAPI and no running server or model.
"""

import asyncio
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import gpu_key  # noqa: E402

KEY = "test-gpu-key"


def call(app, path, authorization=None):
    """The status of one GET request to an ASGI app, without a server."""
    headers = [(b"authorization", authorization.encode())] if authorization is not None else []
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
             "root_path": "", "headers": headers, "client": ("127.0.0.1", 1), "server": ("test", 80)}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


@pytest.fixture
def app():
    from fastapi import FastAPI
    app = FastAPI()
    gpu_key.install(app, {gpu_key.VARIABLE: KEY})

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    @app.get("/v1/models")
    def models():
        return {"data": []}

    return app


@pytest.mark.parametrize("environ", [{}, {gpu_key.VARIABLE: ""}, {gpu_key.VARIABLE: "  "}])
def test_the_start_refuses_a_missing_or_empty_key(environ):
    with pytest.raises(SystemExit, match=gpu_key.VARIABLE):
        gpu_key.read_key(environ)


def test_health_answers_without_the_key(app):
    assert call(app, "/health") == 200


def test_every_other_route_needs_the_key(app):
    assert call(app, "/v1/models") == 401
    assert call(app, "/v1/models", "Bearer wrong") == 401
    assert call(app, "/v1/models", KEY) == 401
    assert call(app, "/missing") == 401
    assert call(app, "/v1/models", "Bearer " + KEY) == 200


def test_the_two_copies_of_the_module_are_equal():
    other = HERE.parent / ("easyocr_server" if HERE.name == "hoover4_ai_server" else "hoover4_ai_server") / "gpu_key.py"
    assert other.read_text() == (HERE / "gpu_key.py").read_text()


def test_the_server_adds_the_check_before_it_serves():
    """The server module adds the check at import, so uvicorn and the image command run it."""
    import ast
    server = HERE / (HERE.name + ".py")
    calls = [node for node in ast.walk(ast.parse(server.read_text()))
             if isinstance(node, ast.Call) and ast.unparse(node.func) == "gpu_key.install"]
    assert [ast.unparse(c) for c in calls] == ["gpu_key.install(app)"]
