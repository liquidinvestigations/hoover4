"""Record single model requests and preserve terminal attempt identities."""

import json
import importlib.util
import os
from pathlib import Path
import platform
import time

import requests
from tasks.llm_endpoints import endpoint_for
from . import ROOT
from .schema import (Invalid, array, boolean, canonical_json, digest, integer, obj,
                     require, string, text_digest)


def _parameter_module(name):
    # These pure modules have no dependency on the agent package initializer.
    path = ROOT / "main_services/agents/research_agent/research_agent" / (name + ".py")
    spec = importlib.util.spec_from_file_location("chat_review_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


send_temperature = _parameter_module("model_params").send_temperature
thinking_body = _parameter_module("thinking").thinking_body


class TransportFailure(Exception):
    """The provider request has no usable transport response."""


def read_json(path):
    return json.loads(Path(path).read_bytes().decode("utf-8"),
                      parse_constant=lambda _: (_ for _ in ()).throw(Invalid("Nonfinite JSON value.")),
                      object_pairs_hook=_unique_object)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON field.")
        result[key] = value
    return result


def write_json(path, value):
    path = Path(path)
    data = canonical_json(value) + "\n"
    temp = path.with_name(path.name + ".tmp")
    with temp.open("x", encoding="utf-8", newline="") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def implementation_identity():
    paths = sorted((ROOT / "scripts/chat_review").glob("*.py"))
    paths += [ROOT / "main_services/processing" / name for name in (
        "tasks/P_agent/control/model.py", "tasks/P_workspace/selection.py",
        "tasks/P_workspace/references.py", "tasks/P_agent/reports.py",
        "database/agent_runs.py", "database/chat_workspace.py", "tasks/llm_endpoints.py")]
    paths += [ROOT / "main_services/agents/research_agent/research_agent" / name
              for name in ("model_params.py", "thinking.py")]
    return {str(p.relative_to(ROOT)): text_digest(p.read_bytes().decode("utf-8")) for p in paths}


def begin_attempt(out, inputs, resume=False):
    out = Path(out)
    manifest = {"schema_version": 1, "inputs_digest": digest(inputs), "inputs": inputs,
                "implementation": implementation_identity(), "python": platform.python_version()}
    if out.exists():
        require(resume and out.is_dir() and not out.is_symlink(), "Use a new attempt directory.")
        require(read_json(out / "manifest.json") == manifest, "Resume input or implementation identity differs.")
        status = read_json(out / "status.json")
        require(status.get("state") == "complete", "Resume requires a completed attempt. Use a new directory for retries.")
        for name, expected in status["artifacts"].items():
            path = out / name
            require(path.is_file() and not path.is_symlink() and text_digest(path.read_bytes().decode("utf-8")) == expected,
                    "A completed artifact changed or is missing.")
        return status
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / "manifest.json", manifest)
    write_json(out / "status.json", {"state": "started", "outcome": "unknown"})
    return None


def finish_attempt(out, result, code):
    out = Path(out)
    artifacts = {str(p.relative_to(out)): text_digest(p.read_bytes().decode("utf-8"))
                 for p in sorted(out.rglob("*")) if p.is_file() and p != out / "status.json"}
    write_json(out / "status.json", {"state": "complete", "exit_code": code,
                                     "result": result, "artifacts": artifacts})
    return result, code


def validate_config(config):
    obj(config, ("model", "thinking", "max_tokens", "temperature", "response_format",
                 "connect_timeout", "read_timeout", "procedure"), ("files",))
    string(config["model"])
    boolean(config["thinking"])
    integer(config["max_tokens"], 1)
    for k in ("connect_timeout", "read_timeout"):
        require(type(config[k]) in (int, float) and 0 < config[k] < float("inf"), "Timeout must be finite and positive.")
    require(config["temperature"] is None or type(config["temperature"]) in (int, float)
            and 0 <= config["temperature"] <= 2, "Invalid temperature.")
    require(config["temperature"] is None or send_temperature(), "The configured provider refuses temperature.")
    require(config["response_format"] in ("text", "json_object"), "Unsupported response format.")
    require(config["procedure"] in ("fresh", "history", "per_report"), "Unknown review procedure.")
    if config["procedure"] == "per_report":
        require(len(array(config.get("files"))) == 1, "A per-report review requires one file.")
        string(config["files"][0])
    else:
        require("files" not in config, "Only per-report review selects files.")
    return config


def make_request(messages, config):
    validate_config(config)
    body = {"model": config["model"], "messages": messages, "max_tokens": config["max_tokens"],
            "stream": False, **thinking_body(config["thinking"])}
    if config["temperature"] is not None:
        body["temperature"] = config["temperature"]
    if config["response_format"] != "text":
        body["response_format"] = {"type": config["response_format"]}
    return body


def request_review(request, endpoint, output_dir, timeouts=(10, 240)):
    """Send once, without redirects, retries, or credential-bearing error text."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=False)
    require(bool(endpoint.base_url), "No endpoint is configured for this model.")
    write_json(out / "request.json", {"request": request, "request_digest": digest(request),
                                      "timeouts": list(timeouts), "model": request["model"]})
    write_json(out / "status.json", {"state": "submitted", "outcome": "unknown"})
    started = time.monotonic()
    try:
        response = requests.post(endpoint.base_url.rstrip("/") + "/chat/completions",
                                 headers={"Authorization": "Bearer " + endpoint.api_key},
                                 json=request, timeout=timeouts, allow_redirects=False)
    except requests.RequestException as exc:
        write_json(out / "status.json", {"state": "transport_failed", "error_type": type(exc).__name__,
                                         "outcome": "unknown", "elapsed_s": time.monotonic() - started})
        raise TransportFailure("The model transport failed. The server outcome is unknown.") from None
    except KeyboardInterrupt:
        write_json(out / "status.json", {"state": "interrupted", "outcome": "unknown",
                                         "elapsed_s": time.monotonic() - started})
        raise
    elapsed = time.monotonic() - started
    if response.status_code != 200:
        # Error bodies can contain private routes or echoed authentication values.
        write_json(out / "status.json", {"state": "transport_failed", "http_status": response.status_code,
                                         "elapsed_s": elapsed, "body_omitted": True})
        if response.status_code in (400, 422):
            raise Invalid("The provider rejected the request settings.")
        raise TransportFailure("The model returned an unsuccessful HTTP status.")
    raw = response.content.decode("utf-8", errors="replace")
    if endpoint.api_key:
        raw = raw.replace(endpoint.api_key, "<redacted>")
    raw = raw.replace(endpoint.base_url, "<endpoint>")
    (out / "response.json").write_bytes(raw.encode("utf-8"))
    try:
        reply = read_json(out / "response.json")
    except (ValueError, Invalid):
        reply = None
    write_json(out / "status.json", {"state": "received", "http_status": 200,
                                     "elapsed_s": elapsed, "response_digest": text_digest(raw)})
    return reply


def response_content(reply):
    if not isinstance(reply, dict):
        raise Invalid("The response body is not a JSON object.")
    choices = reply.get("choices")
    require(isinstance(choices, list) and len(choices) == 1, "The response requires one choice.")
    choice = choices[0]
    require(isinstance(choice, dict) and choice.get("finish_reason") == "stop", "The response did not finish normally.")
    message = choice.get("message")
    require(isinstance(message, dict) and not message.get("tool_calls"), "The response has no final text.")
    content = string(message.get("content"))
    return json.loads(content, object_pairs_hook=_unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(Invalid("Nonfinite JSON value.")))


class Client:
    def __init__(self, config):
        self.config = validate_config(config)

    def __call__(self, messages, output_dir):
        config = self.config
        return request_review(make_request(messages, config), endpoint_for(config["model"]), output_dir,
                              (config["connect_timeout"], config["read_timeout"]))
