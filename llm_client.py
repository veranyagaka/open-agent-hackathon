
import json
import os
import re
import time
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

load_dotenv()


class NightshiftRequestError(RuntimeError):
    """Sanitized request failure carrying safe transport telemetry."""

    def __init__(self, message, request_metadata):
        super().__init__(message)
        self.request_metadata = dict(request_metadata)


def _sanitized_endpoint(url):
    """Return endpoint origin/path without userinfo, query parameters, or fragment."""
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return None
        host = parts.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = parts.port
        netloc = f"{host}:{port}" if port is not None else host
        versioned_path = re.search(
            r"(/v\d+(?:\.\d+)?)/chat/completions$", parts.path
        )
        path = (
            f"{versioned_path.group(1)}/chat/completions"
            if versioned_path else "/chat/completions"
        )
        return urlunsplit((parts.scheme, netloc, path, "", ""))
    except ValueError:
        return None


def _nightshift_endpoint(base_url):
    """Build the chat endpoint while discarding URL credentials and query data."""
    try:
        parts = urlsplit(base_url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return None
        host = parts.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = parts.port
        netloc = f"{host}:{port}" if port is not None else host
        path = (parts.path.rstrip("/") if parts.path else "") + "/chat/completions"
        return urlunsplit((parts.scheme, netloc, path, "", ""))
    except ValueError:
        return None


def _request_failure(message, metadata, category, outcome):
    metadata.update({
        "request_outcome": outcome,
        "error_category": category,
        "duration_ms": round((time.monotonic() - metadata["_started_at"]) * 1000, 2),
    })
    metadata.pop("_started_at", None)
    raise NightshiftRequestError(message, metadata)


def _setting(*names, default=None):
    """Return the first non-empty environment setting."""
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return default


def _escape_unescaped_json_string_chars(text: str) -> str:
    """Escape unescaped quotes and control characters inside JSON strings."""
    output = []
    in_string = False
    escaped = False
    index = 0

    while index < len(text):
        char = text[index]
        if not in_string:
            output.append(char)
            if char == '"':
                in_string = True
            index += 1
            continue

        if escaped:
            output.append(char)
            escaped = False
            index += 1
            continue

        if char == "\\":
            output.append(char)
            escaped = True
            index += 1
            continue

        if char == '"':
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            next_char = text[lookahead] if lookahead < len(text) else ""
            if not next_char or next_char in ",:}]":
                output.append(char)
                in_string = False
            else:
                output.append('\\"')
            index += 1
            continue

        if ord(char) < 0x20:
            output.append(json.dumps(char)[1:-1])
        else:
            output.append(char)
        index += 1

    return "".join(output)


def _remove_trailing_json_commas(text: str) -> str:
    """Remove commas immediately before a JSON object/array close."""
    output = []
    in_string = False
    escaped = False
    index = 0

    while index < len(text):
        char = text[index]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            output.append(char)
            index += 1
            continue

        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue

        output.append(char)
        index += 1
    return "".join(output)


def _insert_missing_json_commas(text: str) -> str:
    """Repair missing separators only where the JSON parser identifies a boundary."""
    candidate = text
    value_starts = '"{[-0123456789tfn'
    value_ends = '"}]0123456789el'

    for _ in range(len(candidate)):
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError as exc:
            if exc.msg != "Expecting ',' delimiter":
                return candidate

            previous = exc.pos - 1
            while previous >= 0 and candidate[previous].isspace():
                previous -= 1
            following = exc.pos
            while following < len(candidate) and candidate[following].isspace():
                following += 1

            if (
                previous < 0
                or following >= len(candidate)
                or candidate[previous] not in value_ends
                or candidate[following] not in value_starts
            ):
                return candidate

            candidate = candidate[:previous + 1] + "," + candidate[previous + 1:]

    return candidate


def _parse_agent_json(content: str, finish_reason, model: str) -> dict:
    """Parse model JSON, applying only unambiguous syntax repairs."""
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        if finish_reason == "length":
            detail = "The response may be truncated; increase the token budget or retry."
        else:
            detail = "The response did not contain a complete JSON object."
        raise RuntimeError(
            f"Nightshift returned unusable JSON: {detail} "
            f"(finish_reason={finish_reason}, requested_model={model}). "
            "No fields were inferred or filled."
        )

    candidate = cleaned[start:end + 1]
    candidates = [candidate]
    repaired_strings = _escape_unescaped_json_string_chars(candidate)
    candidates.append(repaired_strings)
    candidates.append(_remove_trailing_json_commas(repaired_strings))
    candidates.append(_insert_missing_json_commas(candidate))
    candidates.append(_insert_missing_json_commas(repaired_strings))

    last_error = None
    for candidate_to_parse in candidates:
        try:
            parsed = json.loads(candidate_to_parse)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if isinstance(parsed, dict):
            return parsed
        raise RuntimeError(
            "Nightshift answer must be a JSON object "
            f"(finish_reason={finish_reason}, requested_model={model})."
        )

    if finish_reason == "length":
        detail = "The response may be truncated; increase the token budget or retry."
    elif last_error is not None and last_error.pos >= len(candidate.rstrip()):
        detail = "The response ended before the JSON object was complete."
    else:
        detail = "The response contains malformed JSON that could not be safely repaired."
    position = last_error.pos if last_error is not None else "unknown"
    raise RuntimeError(
        f"Nightshift returned unusable JSON: {detail} "
        f"(finish_reason={finish_reason}, requested_model={model}, "
        f"parse_position={position}). No fields were inferred or filled."
    )


def ask_agent(system_prompt: str, payload: dict) -> dict:
    """
    Send an agent request through Meterless Nightshift.
    Returns the JSON object expected by the existing StockWhy agents.
    """
    if os.getenv("SAMPLE_MODE", "false").strip().lower() == "true":
        from agents.sample_provider import respond

        return respond(system_prompt, payload)

    model = _setting(
        "METERLESS_MODEL_DEEP",
        "METERLESS_MODEL",
        "METERLESS_MODEL_FAST",
        default="meterless/auto",
    )
    metadata = {
        "correlation_id": str(uuid.uuid4()),
        "provider": "Meterless Nightshift",
        "requested_model": model,
        "served_model": None,
        "endpoint": None,
        "http_status": None,
        "duration_ms": 0,
        "request_outcome": "not_attempted",
        "request_attempted": False,
        "response_received": False,
        "response_parsed": False,
    }
    metadata["_started_at"] = time.monotonic()

    base_url = _setting("METERLESS_BASE_URL")
    token = _setting("METERLESS_RUNTIME_TOKEN")
    if not base_url:
        _request_failure(
            "METERLESS_BASE_URL is missing from .env",
            metadata,
            "configuration_missing",
            "not_attempted",
        )
    if not token:
        _request_failure(
            "METERLESS_RUNTIME_TOKEN is missing from .env",
            metadata,
            "configuration_missing",
            "not_attempted",
        )

    url = _nightshift_endpoint(base_url)
    if url is None:
        _request_failure(
            "METERLESS_BASE_URL must be a valid HTTP(S) URL.",
            metadata,
            "configuration_invalid",
            "not_attempted",
        )
    metadata["endpoint"] = _sanitized_endpoint(url)
    if metadata["endpoint"] is None:
        _request_failure(
            "METERLESS_BASE_URL must be a valid HTTP(S) URL.",
            metadata,
            "configuration_invalid",
            "not_attempted",
        )
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    system_prompt
                    + "\n\nReturn ONLY one valid JSON object. "
                    "Do not wrap it in Markdown fences."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, default=str),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
    }

    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "meterless-app": "stockwhy",
            "meterless-scope": "user",
        },
        method="POST",
    )

    metadata["request_attempted"] = True
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            status_code = getattr(response, "status", None)
            metadata["http_status"] = (
                status_code if isinstance(status_code, int) else None
            )
            metadata["response_received"] = True
            try:
                response_body = response.read().decode("utf-8")
            except UnicodeDecodeError:
                _request_failure(
                    "Nightshift returned a non-UTF-8 response envelope.",
                    metadata,
                    "invalid_response_encoding",
                    "response_parse_failed",
                )
            try:
                result = json.loads(response_body)
            except json.JSONDecodeError as exc:
                _request_failure(
                    "Nightshift returned an invalid JSON response envelope. "
                    "Response content was not logged.",
                    metadata,
                    "invalid_response_envelope",
                    "response_parse_failed",
                )
    except urllib.error.HTTPError as exc:
        metadata["http_status"] = exc.code
        metadata["response_received"] = True
        _request_failure(
            f"Nightshift returned HTTP {exc.code}. Check the Runtime status, "
            "token, and configured model lane.",
            metadata,
            "http_error",
            "http_error",
        )
    except urllib.error.URLError as exc:
        _request_failure(
            "Could not reach Nightshift Runtime. Check that it is running and "
            "that METERLESS_BASE_URL is correct.",
            metadata,
            "transport_error",
            "transport_error",
        )
    except TimeoutError:
        _request_failure(
            "Nightshift timed out after 180 seconds. Retry once; "
            "do not switch providers silently.",
            metadata,
            "timeout",
            "timeout",
        )

    if not isinstance(result, dict):
        _request_failure(
            "Nightshift returned a non-object JSON envelope.",
            metadata,
            "invalid_response_envelope",
            "response_parse_failed",
        )

    choices = result.get("choices") or []
    if not choices:
        _request_failure(
            "Nightshift returned no choices.",
            metadata,
            "invalid_response_envelope",
            "response_parse_failed",
        )

    if not isinstance(choices[0], dict):
        _request_failure(
            "Nightshift returned a malformed choice.",
            metadata,
            "invalid_response_envelope",
            "response_parse_failed",
        )
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        _request_failure(
            "Nightshift returned a malformed message.",
            metadata,
            "invalid_response_envelope",
            "response_parse_failed",
        )
    content = message.get("content")

    # Some reasoning models return reasoning separately and no final answer
    # when the token budget is exhausted. Do not treat that as valid JSON.
    if not isinstance(content, str) or not content.strip():
        finish_reason = choices[0].get("finish_reason")
        _request_failure(
            "Nightshift returned an empty answer "
            f"(finish_reason={finish_reason}, requested_model={model}). "
            "Check the configured model lane and token budget.",
            metadata,
            "empty_model_response",
            "response_parse_failed",
        )

    content = content.strip()
    try:
        parsed = _parse_agent_json(
            content,
            finish_reason=choices[0].get("finish_reason"),
            model=model,
        )
    except RuntimeError as exc:
        _request_failure(
            f"{exc} Response content was not logged.",
            metadata,
            "malformed_model_response",
            "response_parse_failed",
        )

    # Treat provider metadata as transport data, not model-controlled output.
    parsed["_provider"] = "Meterless Nightshift"
    parsed["_requested_model"] = model
    served_model = result.get("model")
    parsed["_served_model"] = (
        served_model.strip()
        if isinstance(served_model, str) and served_model.strip()
        else None
    )
    metadata.update({
        "served_model": parsed["_served_model"],
        "http_status": metadata["http_status"] or 200,
        "duration_ms": round((time.monotonic() - metadata["_started_at"]) * 1000, 2),
        "request_outcome": "success",
        "response_parsed": True,
    })
    metadata.pop("_started_at", None)
    parsed["_request_metadata"] = metadata
    if message.get("reasoning_content") is not None:
        parsed["_reasoning_content"] = message["reasoning_content"]
    return parsed
