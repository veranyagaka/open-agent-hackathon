"""
llm_client.py

The single place StockWhy agents talk to a language model.

Nightshift contract used
------------------------
Meterless Nightshift is the primary (and only) AI provider. It exposes an
OpenAI-compatible endpoint on the user's machine:

  POST {METERLESS_BASE_URL}/chat/completions
       METERLESS_BASE_URL defaults to http://127.0.0.1:8088/v1
  Headers:
       Authorization: Bearer {METERLESS_RUNTIME_TOKEN}
       meterless-app: stockwhy
       meterless-scope: user
       Content-Type: application/json
  Body: {"model", "messages", "temperature", "max_tokens"}
  Models (lanes):
       deep -> METERLESS_MODEL_DEEP (default "meterless/deep")
       fast -> METERLESS_MODEL_FAST (default "meterless/fast")
       auto -> "meterless/auto" (Nightshift's own router)
       NVIDIA Nemotron is reached through these lanes.
  Response: choices[0].message.content is the answer;
       choices[0].message.reasoning_content holds Nemotron's reasoning;
       choices[0].finish_reason; top-level "model" is the model that served it.

Nemotron reasons before it answers. With a small token budget it spends the
whole budget reasoning and returns content=null with finish_reason="length".
We therefore send a generous max_tokens and retry once with double the budget
when the answer is empty. HTTP 429/5xx get a bounded backoff (max 2 retries).
Every HTTP request counts against a per-run budget
(STOCKWHY_MAX_LLM_CALLS, default 30) to respect free-endpoint rate limits;
reset_call_budget() starts a fresh budget and is called at the start of
every run (orchestrator, run.py CLI and each /run request). One call to
ask_agent() also has an overall deadline (STOCKWHY_LLM_DEADLINE_S, default
300 s) covering retries and backoff.

Answers may start with a <think>...</think> block (or an unclosed leading
<think>); it is stripped before the JSON object is recovered.

Offline mode
------------
llm_enabled() is the one switch: STOCKWHY_USE_LLM if set, otherwise
"not SAMPLE_MODE". SAMPLE_MODE=true always forces it off (judges' offline run), even when
STOCKWHY_USE_LLM=true. When it is False the agents run their rule-based
logic on the computed evidence and never call this module's network code.

Every answer carries metadata the orchestrator can log:
  _provider, _requested_model, _served_model, _lane, _retries, _latency_ms,
  _finish_reason, _reasoning_chars, _max_tokens, _produced_by,
  _route_headers (meterless-* / x-* response headers)
and the same facts without the underscore: "model" (the served model as the
response reported it, or "unreported"), "requested_model", "route_headers".
_served_model / _produced_by fall back to the requested model so traces
still name a lane when the response omits "model".
"""

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("stockwhy.llm")

PROVIDER = "Meterless Nightshift"
RULE_BASED = "rule-based"
DEFAULT_BASE_URL = "http://127.0.0.1:8088/v1"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_MAX_CALLS = 30
DEFAULT_DEADLINE_S = 300.0
PLACEHOLDER_TOKENS = {"replace_with_your_runtime_token"}
UNREPORTED = "unreported"
MAX_HTTP_RETRIES = 2
_TRUE = {"1", "true", "yes", "on"}

# Seam for tests: patched so backoff does not actually sleep.
_sleep = time.sleep

_call_lock = threading.Lock()
_calls_made = 0


class LLMError(RuntimeError):
    """A one-line, user-readable LLM failure."""


class LLMCallCapReached(LLMError):
    """The per-run LLM call budget is spent."""


def _setting(*names, default=None):
    """Return the first non-empty environment setting."""
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return default


def _one_line(text, limit: int = 200) -> str:
    return " ".join(str(text).split())[:limit]


# ---------------------------------------------------------------------------
# Switch and budget
# ---------------------------------------------------------------------------

def llm_enabled() -> bool:
    """
    The single on/off switch for LLM calls.

    SAMPLE_MODE=true always means off (judges' offline run). Otherwise
    STOCKWHY_USE_LLM wins when set (true/false), and the default is on.
    """
    if os.getenv("SAMPLE_MODE", "false").strip().lower() in _TRUE:
        return False
    explicit = os.getenv("STOCKWHY_USE_LLM")
    if explicit is not None and explicit.strip():
        return explicit.strip().lower() in _TRUE
    return True


def max_llm_calls() -> int:
    try:
        return max(0, int(_setting("STOCKWHY_MAX_LLM_CALLS", default=DEFAULT_MAX_CALLS)))
    except ValueError:
        return DEFAULT_MAX_CALLS


def calls_made() -> int:
    """HTTP requests sent to Nightshift since the last reset."""
    return _calls_made


def reset_call_budget() -> None:
    """Reset the call counter (call once at the start of each run)."""
    global _calls_made
    with _call_lock:
        _calls_made = 0


def _take_call() -> None:
    global _calls_made
    with _call_lock:
        cap = max_llm_calls()
        if _calls_made >= cap:
            raise LLMCallCapReached(
                f"LLM call cap reached ({cap} calls, STOCKWHY_MAX_LLM_CALLS); "
                "no further Nightshift requests this run."
            )
        _calls_made += 1


def base_url() -> str:
    """METERLESS_BASE_URL normalised to <scheme://host[:port]>/v1 (never /v1/v1)."""
    raw = _setting("METERLESS_BASE_URL", default=DEFAULT_BASE_URL).rstrip("/")
    for suffix in ("/chat/completions", "/chat"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)].rstrip("/")
    while raw.endswith("/v1/v1"):
        raw = raw[:-3]
    if not raw.endswith("/v1"):
        raw += "/v1"
    return raw


def _deadline_seconds() -> float:
    try:
        return max(1.0, float(_setting("STOCKWHY_LLM_DEADLINE_S", default=DEFAULT_DEADLINE_S)))
    except ValueError:
        return DEFAULT_DEADLINE_S


def _route_headers(headers) -> dict:
    """Routing facts Nightshift reports in response headers (meterless-* and x-*)."""
    out = {}
    for key, value in (headers.items() if headers else []):
        low = key.lower()
        if low.startswith("meterless-") or low.startswith("x-"):
            out[low] = _one_line(value, 200)
    return out


def model_for_lane(lane: str = "deep") -> str:
    lane = (lane or "deep").strip().lower()
    if lane == "deep":
        return _setting("METERLESS_MODEL_DEEP", "METERLESS_MODEL", default="meterless/deep")
    if lane == "fast":
        return _setting("METERLESS_MODEL_FAST", default="meterless/fast")
    if lane == "auto":
        return "meterless/auto"
    raise ValueError(f"Unknown LLM lane {lane!r}; use 'deep', 'fast' or 'auto'.")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _backoff_seconds(attempt: int, retry_after) -> float:
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), 30.0)
        except ValueError:
            pass
    try:
        base = float(_setting("STOCKWHY_LLM_BACKOFF_S", default="2"))
    except ValueError:
        base = 2.0
    return min(base * (2 ** attempt), 20.0)


def _post(url: str, body: dict, headers: dict, deadline: float = None) -> tuple:
    """
    POST the request, retrying HTTP 429/5xx up to MAX_HTTP_RETRIES times.
    `deadline` is a time.monotonic() value no request or backoff may pass.
    Returns (response_json, http_retries, route_headers).
    """
    try:
        timeout = float(_setting("STOCKWHY_LLM_TIMEOUT_S", default="180"))
    except ValueError:
        timeout = 180.0
    data = json.dumps(body).encode("utf-8")
    retries = 0
    while True:
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise LLMError(
                f"Nightshift call deadline passed ({_deadline_seconds():.0f}s, "
                "STOCKWHY_LLM_DEADLINE_S); giving up on this step."
            )
        _take_call()
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(
                request, timeout=timeout if remaining is None else max(1.0, min(timeout, remaining))
            ) as response:
                raw = response.read().decode("utf-8")
                route = _route_headers(response.headers)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            transient = exc.code == 429 or 500 <= exc.code < 600
            if transient and retries < MAX_HTTP_RETRIES:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                wait = _backoff_seconds(retries, retry_after)
                if deadline is not None and time.monotonic() + wait > deadline:
                    raise LLMError(
                        f"Nightshift returned HTTP {exc.code} and the retry would pass the "
                        f"{_deadline_seconds():.0f}s deadline (STOCKWHY_LLM_DEADLINE_S)."
                    ) from None
                log.warning("nightshift HTTP %s; retry %d in %.1fs", exc.code, retries + 1, wait)
                retries += 1
                _sleep(wait)
                continue
            raise LLMError(
                f"Nightshift returned HTTP {exc.code} for model {body.get('model')}: "
                f"{_one_line(detail) or exc.reason}"
            ) from None
        except urllib.error.URLError as exc:
            raise LLMError(
                f"Could not reach Nightshift at {url} ({_one_line(exc.reason, 120)}). "
                "Start Nightshift Runtime, or run offline with SAMPLE_MODE=true."
            ) from None
        except (TimeoutError, OSError) as exc:
            raise LLMError(
                f"Nightshift request failed ({_one_line(exc, 120)}) with a {timeout:.0f}s "
                "timeout. Retry; StockWhy does not switch providers silently."
            ) from None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise LLMError(
                f"Nightshift sent a non-JSON response: {_one_line(raw, 120)!r}"
            ) from None
        if not isinstance(parsed, dict):
            raise LLMError(f"Nightshift sent a {type(parsed).__name__}, not a JSON object.")
        return parsed, retries, route


# ---------------------------------------------------------------------------
# Answer parsing
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_THINK = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def strip_think(text: str) -> str:
    """Drop <think>...</think> blocks, and an unclosed leading <think> up to the first '{'."""
    text = _THINK.sub("", text)
    stripped = text.lstrip()
    if stripped.lower().startswith("<think>"):
        brace = stripped.find("{")
        text = stripped[brace:] if brace >= 0 else ""
    return text.replace("</think>", "").strip()


def parse_json_object(content, served_model: str = "?") -> dict:
    """Recover one JSON object from a model answer (think blocks, fences or prose allowed)."""
    if not isinstance(content, str):
        raise LLMError(
            f"Nightshift answer from {served_model} was a {type(content).__name__}, not text."
        )
    text = strip_think(content)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None and not isinstance(parsed, dict):
        raise LLMError(
            f"Expected a JSON object from {served_model}, received {type(parsed).__name__}."
        )
    if isinstance(parsed, dict):
        return parsed
    for block in _FENCE.finditer(text):
        try:
            fenced = json.loads(block.group(1).strip())
        except json.JSONDecodeError:
            continue
        if isinstance(fenced, dict):
            return fenced

    # Decode at every "{" and keep the last object that parses (the answer
    # usually follows any prose or echoed braces).
    decoder = json.JSONDecoder()
    last = None
    pos = text.find("{")
    while pos >= 0:
        try:
            obj, _end = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            last = obj
        pos = text.find("{", pos + 1)
    if last is not None:
        return last
    raise LLMError(
        f"Nightshift answer from {served_model} was not valid JSON; "
        f"answer begins: {_one_line(text, 120)!r}"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ask_agent(
    system_prompt: str,
    payload: dict,
    lane: str = "deep",
    max_tokens: int = None,
) -> dict:
    """
    Send an agent request through Meterless Nightshift and return the
    parsed JSON object plus metadata keys (see module docstring).

    Raises LLMError (one-line message) on any failure.
    """
    token = _setting("METERLESS_RUNTIME_TOKEN")
    model = model_for_lane(lane)
    if not token:
        raise LLMError(
            "METERLESS_RUNTIME_TOKEN is not set. Copy it from Nightshift into .env, "
            "or run offline with SAMPLE_MODE=true."
        )
    if token in PLACEHOLDER_TOKENS:
        raise LLMError(
            "METERLESS_RUNTIME_TOKEN still holds the .env.example placeholder. Paste the "
            "real token from Nightshift, or run offline with SAMPLE_MODE=true."
        )
    try:
        budget = int(max_tokens or _setting("STOCKWHY_LLM_MAX_TOKENS", default=DEFAULT_MAX_TOKENS))
    except ValueError:
        budget = DEFAULT_MAX_TOKENS

    url = base_url() + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "meterless-app": "stockwhy",
        "meterless-scope": "user",
    }
    messages = [
        {
            "role": "system",
            "content": (
                system_prompt
                + "\n\nReturn ONLY one valid JSON object. "
                "Do not wrap it in Markdown fences."
            ),
        },
        {"role": "user", "content": json.dumps(payload, default=str)},
    ]

    started = time.monotonic()
    deadline = started + _deadline_seconds()
    route = {}
    retries = 0
    empty_retry_used = False
    while True:
        body = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": budget}
        result, http_retries, route = _post(url, body, headers, deadline)
        retries += http_retries

        choices = result.get("choices") or []
        if not choices:
            raise LLMError(f"Nightshift returned no choices (keys: {sorted(result)}).")
        choice = choices[0] or {}
        message = choice.get("message") or {}
        content = message.get("content")
        finish_reason = choice.get("finish_reason")
        reported = result.get("model")
        reported = reported.strip() if isinstance(reported, str) and reported.strip() else None
        served = reported or model
        reasoning_chars = len(message.get("reasoning_content") or "")

        log.info(
            "nightshift lane=%s requested=%s served=%s finish=%s "
            "reasoning_chars=%d max_tokens=%d",
            lane, model, served, finish_reason, reasoning_chars, budget,
        )

        if content is not None and not isinstance(content, str):
            raise LLMError(
                f"Nightshift answer from {served} was a {type(content).__name__}, not text."
            )
        if content and strip_think(content):
            break
        if empty_retry_used:
            raise LLMError(
                f"Nightshift returned an empty answer twice (model={served}, "
                f"finish_reason={finish_reason}, max_tokens={budget}, "
                f"reasoning_chars={reasoning_chars})."
            )
        # Nemotron spent the whole budget reasoning; give it room once.
        empty_retry_used = True
        retries += 1
        budget *= 2

    parsed = parse_json_object(content, served)
    parsed["_provider"] = PROVIDER
    parsed["_requested_model"] = model
    parsed["_served_model"] = served
    parsed["_lane"] = lane
    parsed["_retries"] = retries
    parsed["_latency_ms"] = int((time.monotonic() - started) * 1000)
    parsed["_finish_reason"] = finish_reason
    parsed["_reasoning_chars"] = reasoning_chars
    parsed["_max_tokens"] = budget
    parsed["_produced_by"] = served
    parsed["_route_headers"] = route
    parsed["model"] = reported or UNREPORTED
    parsed["requested_model"] = model
    parsed["route_headers"] = route
    return parsed
