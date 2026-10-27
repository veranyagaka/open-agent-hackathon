import json
import urllib.error
from unittest.mock import MagicMock

import pytest

from llm_client import ask_agent


def _response(body):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(body).encode()
    response.status = 200
    return response


def test_sample_mode_uses_local_provider_without_nightshift_credentials(monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "true")
    monkeypatch.setenv("METERLESS_BASE_URL", "")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "")

    result = ask_agent(
        "You are the StockyWhy Data Analyst.",
        {"computed_evidence": {}},
    )

    assert result["_provider"] == "StockWhy offline sample provider"
    assert result["_served_model"] is None
    assert "analysis_summary" in result


def test_nightshift_requires_configuration_without_sample_mode(monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("METERLESS_BASE_URL", "")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "")

    with pytest.raises(RuntimeError, match="METERLESS_BASE_URL"):
        ask_agent("system", {})


def test_nightshift_client_uses_documented_contract_and_trusted_model_metadata(
    monkeypatch,
):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("METERLESS_BASE_URL", "http://127.0.0.1:8088/v1")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "unit-test-token")
    monkeypatch.setenv(
        "METERLESS_MODEL_DEEP", "nvidia/nemotron-3.5-lightning-30b-a3b"
    )
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _response({
            "model": "nvidia/nemotron-3.5-lightning-30b-a3b",
            "choices": [{
                "message": {
                    "content": '{"answer":"ok","_provider":"spoofed",'
                    '"_served_model":"spoofed"}',
                    "reasoning_content": "test reasoning",
                },
                "finish_reason": "stop",
            }],
        })

    monkeypatch.setattr("llm_client.urllib.request.urlopen", fake_urlopen)
    result = ask_agent("system", {"question": "test"})

    request = captured["request"]
    headers = {key.lower(): value for key, value in request.header_items()}
    body = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "http://127.0.0.1:8088/v1/chat/completions"
    assert headers["authorization"] == "Bearer unit-test-token"
    assert headers["meterless-app"] == "stockwhy"
    assert headers["meterless-scope"] == "user"
    assert body["model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert captured["timeout"] == 180
    assert result["answer"] == "ok"
    assert result["_provider"] == "Meterless Nightshift"
    assert result["_served_model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert result["_reasoning_content"] == "test reasoning"
    telemetry = result["_request_metadata"]
    assert telemetry["provider"] == "Meterless Nightshift"
    assert telemetry["requested_model"] == (
        "nvidia/nemotron-3.5-lightning-30b-a3b"
    )
    assert telemetry["served_model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert telemetry["endpoint"] == "http://127.0.0.1:8088/v1/chat/completions"
    assert telemetry["http_status"] == 200
    assert telemetry["request_outcome"] == "success"
    assert telemetry["request_attempted"] is True
    assert telemetry["response_received"] is True
    assert telemetry["response_parsed"] is True
    assert telemetry["duration_ms"] >= 0
    assert telemetry["correlation_id"]


def test_nightshift_endpoint_metadata_excludes_url_credentials_and_query(monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv(
        "METERLESS_BASE_URL",
        "https://user:password@example.test/private-secret/v1?api_key=secret",
    )
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "unit-test-token")
    monkeypatch.setattr(
        "llm_client.urllib.request.urlopen",
        lambda request, timeout: _response({
            "model": "meterless/test",
            "choices": [{
                "message": {"content": '{"ok":true}'},
                "finish_reason": "stop",
            }],
        }),
    )

    result = ask_agent("private prompt", {})
    metadata = result["_request_metadata"]

    assert metadata["endpoint"] == "https://example.test/v1/chat/completions"
    serialized = json.dumps(metadata)
    assert "password" not in serialized
    assert "private-secret" not in serialized
    assert "api_key" not in serialized
    assert "unit-test-token" not in serialized
    assert "private prompt" not in serialized


def test_nightshift_http_failure_has_sanitized_attempt_metadata(monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("METERLESS_BASE_URL", "http://localhost:8088/v1")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "unit-test-token")

    def fail_request(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 503, "unavailable", {}, None
        )

    monkeypatch.setattr("llm_client.urllib.request.urlopen", fail_request)

    with pytest.raises(RuntimeError, match="HTTP 503") as error:
        ask_agent("private prompt", {})

    metadata = error.value.request_metadata
    assert metadata["request_attempted"] is True
    assert metadata["response_received"] is True
    assert metadata["response_parsed"] is False
    assert metadata["http_status"] == 503
    assert metadata["request_outcome"] == "http_error"
    assert metadata["error_category"] == "http_error"
    assert metadata["correlation_id"]
    assert "unit-test-token" not in json.dumps(metadata)
    assert "private prompt" not in str(error.value)


def test_nightshift_malformed_model_response_records_parse_failure(monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("METERLESS_BASE_URL", "http://localhost:8088/v1")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "unit-test-token")
    private_output = '{"secret":"do not log",'
    monkeypatch.setattr(
        "llm_client.urllib.request.urlopen",
        lambda request, timeout: _response({
            "model": "meterless/test",
            "choices": [{
                "message": {"content": private_output},
                "finish_reason": "stop",
            }],
        }),
    )

    with pytest.raises(RuntimeError, match="unusable JSON") as error:
        ask_agent("private prompt", {})

    metadata = error.value.request_metadata
    assert metadata["request_attempted"] is True
    assert metadata["response_received"] is True
    assert metadata["response_parsed"] is False
    assert metadata["request_outcome"] == "response_parse_failed"
    assert metadata["error_category"] == "malformed_model_response"
    assert private_output not in str(error.value)
    assert "private prompt" not in str(error.value)


def test_nightshift_parser_repairs_unescaped_quotes_in_generated_text(monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("METERLESS_BASE_URL", "http://localhost:8088/v1")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "unit-test-token")
    content = (
        '{"analysis_summary":"The analyst reported a "strong" signal.",'
        '"hypothesis_signals":{"H4":{"signal":"strong",'
        '"reasoning":"The source note contains "urgent" wording."}},'
        '"primary_leads":["H4"],"data_limitations":[]}'
    )
    monkeypatch.setattr(
        "llm_client.urllib.request.urlopen",
        lambda request, timeout: _response({
            "model": "meterless/test",
            "choices": [{
                "message": {"content": content},
                "finish_reason": "stop",
            }],
        }),
    )

    result = ask_agent("system", {})

    assert result["analysis_summary"] == 'The analyst reported a "strong" signal.'
    assert result["hypothesis_signals"]["H4"]["reasoning"] == (
        'The source note contains "urgent" wording.'
    )
    assert result["primary_leads"] == ["H4"]


def test_nightshift_parser_accepts_fenced_json_with_prose_and_trailing_commas(
    monkeypatch,
):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("METERLESS_BASE_URL", "http://localhost:8088/v1")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "unit-test-token")
    monkeypatch.setattr(
        "llm_client.urllib.request.urlopen",
        lambda request, timeout: _response({
            "choices": [{
                "message": {
                    "content": (
                        'Result follows:\n```json\n{"analysis_summary":"ok",'
                        '"values":[1,2,],}\n```\n'
                    )
                },
                "finish_reason": "stop",
            }],
        }),
    )

    result = ask_agent("system", {})

    assert result["analysis_summary"] == "ok"
    assert result["values"] == [1, 2]


def test_nightshift_parser_repairs_missing_commas_without_changing_values(
    monkeypatch,
):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("METERLESS_BASE_URL", "http://localhost:8088/v1")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "unit-test-token")
    content = (
        '{"theories":[{"id":"H1","hypothesis_name":"late_order",'
        '"title":"Late order" "mechanism":"The order arrived late.",'
        '"evidence_needed":["cutoff date","delivery date"]}]}'
    )
    monkeypatch.setattr(
        "llm_client.urllib.request.urlopen",
        lambda request, timeout: _response({
            "choices": [{
                "message": {"content": content},
                "finish_reason": "stop",
            }],
        }),
    )

    result = ask_agent("system", {})

    assert result["theories"] == [{
        "id": "H1",
        "hypothesis_name": "late_order",
        "title": "Late order",
        "mechanism": "The order arrived late.",
        "evidence_needed": ["cutoff date", "delivery date"],
    }]


def test_nightshift_parser_rejects_truncated_json_without_filling_fields(monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("METERLESS_BASE_URL", "http://localhost:8088/v1")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "unit-test-token")
    monkeypatch.setattr(
        "llm_client.urllib.request.urlopen",
        lambda request, timeout: _response({
            "model": "meterless/test",
            "choices": [{
                "message": {"content": '{"analysis_summary":"partial'},
                "finish_reason": "length",
            }],
        }),
    )

    with pytest.raises(
        RuntimeError,
        match="truncated.*No fields were inferred or filled",
    ) as error:
        ask_agent("system", {})
    assert "partial" not in str(error.value)
    assert "unit-test-token" not in str(error.value)


def test_nightshift_parser_does_not_invent_fields_for_valid_partial_json(monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("METERLESS_BASE_URL", "http://localhost:8088/v1")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "unit-test-token")
    monkeypatch.setattr(
        "llm_client.urllib.request.urlopen",
        lambda request, timeout: _response({
            "choices": [{
                "message": {"content": '{"analysis_summary":"partial but valid"}'},
                "finish_reason": "stop",
            }],
        }),
    )

    result = ask_agent("system", {})

    assert result["analysis_summary"] == "partial but valid"
    assert "hypothesis_signals" not in result


def test_nightshift_rejects_invalid_response_envelope_without_body(monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("METERLESS_BASE_URL", "http://localhost:8088/v1")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "unit-test-token")
    response = MagicMock()
    response.__enter__.return_value.read.return_value = (
        b'{"choices":"prompt or credential data'
    )
    monkeypatch.setattr(
        "llm_client.urllib.request.urlopen",
        lambda request, timeout: response,
    )

    with pytest.raises(RuntimeError, match="invalid JSON response envelope") as error:
        ask_agent("private prompt text", {})
    assert "credential data" not in str(error.value)
    assert "private prompt text" not in str(error.value)


def test_nightshift_transport_errors_do_not_disclose_configured_url(monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv(
        "METERLESS_BASE_URL", "http://private-user:private-pass@example.test/v1"
    )
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "unit-test-token")
    monkeypatch.setattr(
        "llm_client.urllib.request.urlopen",
        lambda request, timeout: (_ for _ in ()).throw(
            urllib.error.URLError("connection refused")
        ),
    )

    with pytest.raises(RuntimeError) as error:
        ask_agent("system", {})

    assert "private-user" not in str(error.value)
    assert "private-pass" not in str(error.value)
    assert "unit-test-token" not in str(error.value)


def test_nightshift_http_failures_report_status_without_response_body(monkeypatch):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("METERLESS_BASE_URL", "http://localhost:8088/v1")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "unit-test-token")
    monkeypatch.setattr(
        "llm_client.urllib.request.urlopen",
        lambda request, timeout: (_ for _ in ()).throw(
            urllib.error.HTTPError(
                request.full_url,
                429,
                "rate limited",
                {},
                None,
            )
        ),
    )

    with pytest.raises(RuntimeError, match="HTTP 429"):
        ask_agent("system", {})


@pytest.mark.parametrize(
    "body, message",
    [
        ({"choices": []}, "no choices"),
        ({"choices": [{"message": {"content": None}}]}, "empty answer"),
    ],
)
def test_nightshift_malformed_responses_fail_explicitly(monkeypatch, body, message):
    monkeypatch.setenv("SAMPLE_MODE", "false")
    monkeypatch.setenv("METERLESS_BASE_URL", "http://localhost:8088/v1")
    monkeypatch.setenv("METERLESS_RUNTIME_TOKEN", "unit-test-token")
    monkeypatch.setattr(
        "llm_client.urllib.request.urlopen",
        lambda request, timeout: _response(body),
    )

    with pytest.raises(RuntimeError, match=message):
        ask_agent("system", {})
