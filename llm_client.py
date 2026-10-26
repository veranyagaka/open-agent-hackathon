
import json
import os
import re
import urllib.error
import urllib.request

from dotenv import load_dotenv

load_dotenv()


def _setting(*names, default=None):
    """Return the first non-empty environment setting."""
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return default


def ask_agent(system_prompt: str, payload: dict) -> dict:
    """
    Send an agent request through Meterless Nightshift.
    Returns the JSON object expected by the existing StockWhy agents.
    """
    base_url = _setting("METERLESS_BASE_URL")
    token = _setting("METERLESS_RUNTIME_TOKEN")

    # Prefer the deep lane for reasoning. Fall back to the fast lane,
    # then the documented Nightshift router if neither is configured.
    model = _setting(
        "METERLESS_MODEL_DEEP",
        "METERLESS_MODEL",
        "METERLESS_MODEL_FAST",
        default="meterless/auto",
    )

    if not base_url:
        raise RuntimeError("METERLESS_BASE_URL is missing from .env")
    if not token:
        raise RuntimeError("METERLESS_RUNTIME_TOKEN is missing from .env")

    url = base_url.rstrip("/") + "/chat/completions"
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

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Nightshift returned HTTP {exc.code}: {detail[:1000]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Nightshift at {url}: {exc.reason}. "
            "Check that Nightshift Runtime is running and the URL is correct."
        ) from exc
    except TimeoutError as exc:
        raise RuntimeError(
            "Nightshift timed out after 180 seconds. Retry once; "
            "do not switch providers silently."
        ) from exc

    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError(
            f"Nightshift returned no choices. Response keys: {list(result)}"
        )

    message = choices[0].get("message") or {}
    content = message.get("content")

    # Some reasoning models return reasoning separately and no final answer
    # when the token budget is exhausted. Do not treat that as valid JSON.
    if not content or not content.strip():
        finish_reason = choices[0].get("finish_reason")
        raise RuntimeError(
            "Nightshift returned an empty answer "
            f"(finish_reason={finish_reason}, model={result.get('model', model)}). "
            "Check the configured model lane and token budget."
        )

    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.IGNORECASE)
    content = re.sub(r"\s*```$", "", content)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Recover a JSON object if the model added a short sentence around it.
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError(
                "Nightshift answer was not valid JSON. "
                f"Model={result.get('model', model)}; "
                f"answer begins: {content[:300]!r}"
            )
        try:
            parsed = json.loads(content[start:end + 1])
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Could not parse Nightshift JSON: {exc}"
            ) from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"Expected a JSON object, received {type(parsed).__name__}"
        )

    # Visible in the returned metadata for demo/audit evidence.
    parsed.setdefault("_provider", "Meterless Nightshift")
    parsed.setdefault("_requested_model", model)
    parsed.setdefault("_served_model", result.get("model", model))
    return parsed
