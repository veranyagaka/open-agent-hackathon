"""
tests/test_llm_client.py

Tests for the Nightshift client against a scripted local HTTP server on
127.0.0.1 (started in-test). No real network endpoint is ever called.
"""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import llm_client
from llm_client import LLMCallCapReached, LLMError, ask_agent


class FakeNightshift:
    """Serves scripted (status, body, headers) responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                fake.requests.append({
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": json.loads(self.rfile.read(length) or b"{}"),
                })
                status, body, headers = fake.responses.pop(0)
                raw = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def completion(content, model="nvidia/nemotron-test", finish="stop", reasoning=None):
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return (200, {"model": model, "choices": [{"message": message, "finish_reason": finish}]}, None)


@pytest.fixture
def nightshift(monkeypatch):
    sleeps = []
    monkeypatch.setattr(llm_client, "_sleep", lambda s: sleeps.append(s))
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "test-token-not-secret")
    for name in ("METERLESS_MODEL_DEEP", "METERLESS_MODEL_FAST", "METERLESS_MODEL",
                 "STOCKWHY_MAX_LLM_CALLS", "STOCKWHY_LLM_MAX_TOKENS", "STOCKWHY_LLM_BACKOFF_S"):
        monkeypatch.delenv(name, raising=False)
    llm_client.reset_call_budget()

    def start(*responses):
        server = FakeNightshift(responses)
        monkeypatch.setenv("METERLESS_BASE_URL", server.base_url)
        server.sleeps = sleeps
        return server

    yield start
    llm_client.reset_call_budget()


def test_contract_headers_lane_and_served_model(nightshift):
    with nightshift(completion('{"ok": true}', model="nvidia/nemotron-x")) as fake:
        result = ask_agent("system", {"q": 1})
    req = fake.requests[0]
    assert req["path"] == "/v1/chat/completions"
    assert req["headers"]["authorization"] == "Bearer test-token-not-secret"
    assert req["headers"]["meterless-app"] == "stockwhy"
    assert req["headers"]["meterless-scope"] == "user"
    assert req["body"]["model"] == "meterless/deep"
    assert req["body"]["max_tokens"] >= 4096
    assert result["ok"] is True
    assert result["_provider"] == "Meterless Nightshift"
    assert result["_requested_model"] == "meterless/deep"
    assert result["_served_model"] == "nvidia/nemotron-x"
    assert result["_produced_by"] == "nvidia/nemotron-x"
    assert result["_retries"] == 0
    assert result["_finish_reason"] == "stop"
    assert isinstance(result["_latency_ms"], int)


def test_fast_lane_uses_fast_model(nightshift, monkeypatch):
    monkeypatch.setenv("METERLESS_MODEL_FAST", "meterless/fast-custom")
    with nightshift(completion('{"a": 1}')) as fake:
        result = ask_agent("s", {}, lane="fast")
    assert fake.requests[0]["body"]["model"] == "meterless/fast-custom"
    assert result["_lane"] == "fast"


def test_null_content_then_success_doubles_budget(nightshift):
    with nightshift(
        completion(None, finish="length", reasoning="thinking " * 50),
        completion('{"answer": 42}'),
    ) as fake:
        result = ask_agent("s", {}, max_tokens=1000)
    assert [r["body"]["max_tokens"] for r in fake.requests] == [1000, 2000]
    assert result["answer"] == 42
    assert result["_retries"] == 1
    assert result["_max_tokens"] == 2000


def test_empty_twice_is_clear_error(nightshift):
    with nightshift(
        completion(None, finish="length", reasoning="r"),
        completion("", finish="length", reasoning="r"),
    ):
        with pytest.raises(LLMError) as err:
            ask_agent("s", {})
    message = str(err.value)
    assert "empty answer" in message and "\n" not in message


def test_429_backoff_then_success(nightshift):
    with nightshift(
        (429, {"error": "rate limited"}, {"Retry-After": "3"}),
        (503, {"error": "busy"}, None),
        completion('{"ok": 1}'),
    ) as fake:
        result = ask_agent("s", {})
    assert len(fake.requests) == 3
    assert result["_retries"] == 2
    assert fake.sleeps[0] == 3.0
    assert len(fake.sleeps) == 2


def test_429_gives_up_after_two_retries(nightshift):
    with nightshift(*[(429, {"error": "rate limited"}, None)] * 3) as fake:
        with pytest.raises(LLMError, match="HTTP 429"):
            ask_agent("s", {})
    assert len(fake.requests) == 3


def test_400_is_not_retried(nightshift):
    with nightshift((400, {"error": "bad model"}, None)) as fake:
        with pytest.raises(LLMError, match="HTTP 400"):
            ask_agent("s", {})
    assert len(fake.requests) == 1


def test_call_cap(nightshift, monkeypatch):
    monkeypatch.setenv("STOCKWHY_MAX_LLM_CALLS", "2")
    with nightshift(completion('{"n": 1}'), completion('{"n": 2}')) as fake:
        ask_agent("s", {})
        ask_agent("s", {})
        with pytest.raises(LLMCallCapReached):
            ask_agent("s", {})
    assert len(fake.requests) == 2
    assert llm_client.calls_made() == 2
    llm_client.reset_call_budget()
    assert llm_client.calls_made() == 0


@pytest.mark.parametrize("content", [
    '```json\n{"x": 1}\n```',
    'Here is the result:\n```\n{"x": 1}\n```\nDone.',
    'Sure. {"x": 1} Hope that helps.',
])
def test_json_recovery(nightshift, content):
    with nightshift(completion(content)):
        assert ask_agent("s", {})["x"] == 1


def test_non_json_answer_is_clear_error(nightshift):
    with nightshift(completion("I cannot answer that.")):
        with pytest.raises(LLMError, match="not valid JSON"):
            ask_agent("s", {})


def test_model_cannot_spoof_metadata(nightshift):
    with nightshift(completion('{"_served_model": "fake", "v": 1}', model="real-model")):
        assert ask_agent("s", {})["_served_model"] == "real-model"


def test_missing_token_is_clear_error(nightshift, monkeypatch):
    monkeypatch.delenv("METERLESS_RUNTIME_TOKEN", raising=False)
    with pytest.raises(LLMError, match="METERLESS_RUNTIME_TOKEN"):
        ask_agent("s", {})


def test_unreachable_is_clear_error(nightshift, monkeypatch):
    server = FakeNightshift([])
    port = server.server.server_port
    server.server.server_close()  # nothing listens on this port now
    monkeypatch.setenv("METERLESS_BASE_URL", f"http://127.0.0.1:{port}/v1")
    with pytest.raises(LLMError, match="Could not reach Nightshift") as err:
        ask_agent("s", {})
    assert "\n" not in str(err.value)


def test_unknown_lane_rejected(nightshift):
    with pytest.raises(ValueError):
        ask_agent("s", {}, lane="turbo")
