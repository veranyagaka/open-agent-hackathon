# NVIDIA Nemotron models

Sources (accessed 2026-10-23):
- Live model list: `GET https://integrate.api.nvidia.com/v1/models` (public, no key; 84 models returned).
- Per-model reference pages: `https://docs.api.nvidia.com/nim/reference/<id with / . replaced by - _>`, e.g. https://docs.api.nvidia.com/nim/reference/nvidia-nemotron-3-super-120b-a12b
- LLM API index: https://docs.api.nvidia.com/nim/reference/llm-apis

Endpoint: "Base URL: `https://integrate.api.nvidia.com`", "Endpoint: `POST /v1/chat/completions`" (LLM API index).
It is OpenAI-compatible. The auth header (`Authorization: Bearer <key>`) is INFERRED from OpenAI compatibility; the
index page doesn't state it.

## Chat / reasoning models

"Tool calling" and "context" quote the model card text on the docs page. JSON mode: no reference page mentions a
`response_format` or `guided_json` parameter, so API-level JSON mode is **NOT FOUND** for every model below. The
"structured output" mentions describe training data, not an API switch.

| Model ID (exact, from /v1/models) | Purpose | Tool calling | JSON mode | Context | Notes |
|---|---|---|---|---|---|
| `nvidia/nemotron-3-super-120b-a12b` | General reasoning / agentic | Card: "tool calling, instruction following, structured outp[ut]" | NOT FOUND | "context length up to 1M tokens" | Probably the best quality/latency balance for our explainer (INFERRED) |
| `nvidia/nemotron-3-ultra-550b-a55b` | Largest Nemotron 3 | Card mentions tool calling; its page is the only one containing `tool_choice` (3 hits) | NOT FOUND | "Context Length Up to 1M tokens" | Slowest/heaviest (INFERRED) |
| `nvidia/nemotron-3.5-super-vl-120b-a12b` | Vision-language reasoning | Card: "Tool Calling, Reasoning Off — SFT" | NOT FOUND | "context lengths up to **1M tokens**" | Could read scanned county budget PDFs (INFERRED) |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | Small and fast | NOT FOUND (no reference page; the URL returns a generic "NIM" page) | NOT FOUND | NOT FOUND | In /v1/models only |
| `nvidia/nemotron-nano-3-30b-a3b` | Small | NOT FOUND (no reference page) | NOT FOUND | NOT FOUND | **Name clash**: the docs page is titled `nemotron-3-nano-30b-a3b`, but /v1/models lists `nemotron-nano-3-30b-a3b`. That page's card: "context length of 256k. You can increase the context size up to 1M" and mentions tool calling. Use the /v1/models spelling |
| `nvidia/llama-3.3-nemotron-super-49b-v1.5` | Llama-based reasoning | Card: "Tool Calling capability enhancements" | NOT FOUND | "Context length up to 131,072 tokens" | Listed in docs but **not in /v1/models** today: may be retired |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | Omni (multimodal) reasoning | NOT FOUND | NOT FOUND | NOT FOUND | In /v1/models only |
| `nvidia/llama-3.1-nemotron-ultra-253b-v1` | Older reasoning | NOT CHECKED | NOT FOUND | NOT CHECKED | In /v1/models |
| `nvidia/llama-3.1-nemotron-70b-instruct`, `nvidia/llama-3.1-nemotron-51b-instruct`, `nvidia/nemotron-4-340b-instruct` | Older instruct | NOT CHECKED | NOT FOUND | NOT CHECKED | In /v1/models; older generation |

## Other Nemotron models in /v1/models (not chat)

| Model ID | Purpose (from name, INFERRED) |
|---|---|
| `nvidia/nemotron-3.5-embed-1b`, `nvidia/nemotron-3.5-embed-8b`, `nvidia/nemotron-3-embed-1b`, `nvidia/llama-nemotron-embed-vl-1b-v2` | Embeddings |
| `nvidia/nemotron-parse`, `nvidia/nemotron-parse-2.0` | Document parsing (PDF → structure): fits extracting county budget PDFs |
| `nvidia/nemotron-3.5-content-safety`, `nvidia/llama-3.1-nemotron-safety-guard-8b-v3` | Safety guardrails |
| `nvidia/nemotron-4-340b-reward` | Reward model |

## Credits and rate limits

- Hackathon-specific NVIDIA credits, or how to claim them: **NOT FOUND** on public pages (may be in HackOS → resources → NVIDIA).
- Rate limit: no official NVIDIA page found. Developer forum posts report "40 RPM" as the free-tier default, and an
  NVIDIA staff reply says the rate "will vary per model queried and may vary based on the number of concurrent users"
  (https://forums.developer.nvidia.com/t/request-for-nvidia-build-api-rate-limit-increase-40-rpm-200-rpm/377433).
  Forum users report that credits have been phased out. Treat both points as unverified until checked on the build.nvidia.com dashboard.

## Meterless and NVIDIA overlap

The Meterless Nightshift DGX edition runs on DGX Spark ("[On request](https://www.meterless.ai/dgx-spark.html)"), and
Meterless says it is an "NVIDIA Inception member". INFERRED: running Nemotron locally behind the Meterless runtime
could earn both the Meterless and the NVIDIA credit, but no rule says so.

## Before building

Call `GET /v1/models` with our key, because the ID list changes. Then test `tools` and `response_format` on the chosen model with one request each.

## HackOS: how NVIDIA must be wired (logged-in pass)

Source: HackOS Resources > Participant Setup Guide, section 03 Power (21 Oct), unless marked.

- NVIDIA is reached **through Meterless Nightshift**, not called directly by the app: "The NVIDIA key goes in
  Providers, not in the Console and not in your app's .env file." "Your app only needs the Meterless URL and the
  Nightshift API key; Nightshift handles the NVIDIA call." Key location: `<present in build.nvidia.com; entered in Nightshift Setup > Providers>`.
- Suggested lanes (exact model names, "examples, not guaranteed entitlements"): "Lane 1: Fast worker
  nvidia/nemotron-3.5-lightning-30b-a3b" and "Lane 2: Deep worker nvidia/nemotron-3.5-super-vl-120b-a12b", plus an
  "Optional judge / verification lane". Both IDs appear in the live `/v1/models` list above.
- Model routing: "meterless/auto is a routing mode, not an NVIDIA model ID." "meterless/auto may route to a non-NVIDIA
  model if several are eligible, so pin a Nemotron-backed lane or demonstrate an explicit Nemotron task". HackOS FAQ:
  "log which model handled each request".
- NVIDIA award (Hackathon Overview): "must use at least one Nemotron model through Meterless Nightshift in a working
  feature, and show which model handled the request." Prize: "NVIDIA DGX Spark (Founder's Edition) | $4,699".
- Credits: NVIDIA sponsor overview says "Credits for NVIDIA Nemotron models, used through API keys" but "Getting
  access" is still "[TBC ...]". HackOS FAQ: "Where do I get sponsor credits? On the HackOS task board, once you have
  created your team." Our team board (read 23 Oct) has a "Get sponsor credits" task with an empty description, so
  **how to claim credits: NOT FOUND**.
- Rate limits: HackOS Escalation Path §7.2 mentions "NVIDIA rate limits" but gives no number. Still **NOT FOUND** officially.
- Judge machines: "No local GPU required; NVIDIA models are reached through Nightshift's hosted endpoints"
  (Disqualification Checklist).

