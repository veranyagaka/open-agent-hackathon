# Sponsor technology in StockyWhy

What each sponsor does in the build, where the code is, and how to see it working.

## Zetaris: the data layer

- **What it does:** in live mode (`STOCKWHY_DATA_SOURCE=zetaris`) the facility stock, orders, payments and
  facilities come from Zetaris over REST (`POST {ZETARIS_REST_URL}/sql-editor/sqls/run`, Bearer key,
  `X-Org-ID`, a fresh `X-Request-ID`, one statement per call). String values are converted back to the same
  types the CSV path produces, so the evidence is identical in both modes (tested).
- **Federation:** two registered datasources. `stockwhy_pg` holds stock, orders, payments and facilities (in real
  life: KHIS, eLMIS, county finance); `stockwhy_web` holds public notices. The national-disruption hypothesis
  combines both.
- **Code:** `tools/data_loader.py` (`load_zetaris_dataset`), `scripts/check_zetaris.py`,
  `scripts/setup_live.py`, `docker-compose.yml`, `data/sample/postgres_load.sql`,
  `data/sample/web_notes_load.sql`, `data/sample/zetaris_register.sql`, `ZETARIS_INTEGRATION.md`.
- **How to see it:** the result's `data_backend` is `zetaris:stockwhy_pg`, and the `load_dataset` trace event
  names the source and row counts.

## Meterless engines: Scout Intent and H-MEM

Implemented in Python from the specs at https://github.com/meterless/meterless ("The contracts do not change").

**Scout Intent** (`engines/scout_intent.py`, registry `engines/intents.json`)
- Guard: instruction override, role confusion, control bytes, exfiltration, injection hidden in data fields.
  Request text is screened before anything parses it; public notices are scanned before they count as evidence.
- Interpret: binds facility, medicine and month to values that exist in the data ("fac 9" → `FAC-009`); asks a
  clarifying question when one is missing.
- Route: refuses out-of-scope asks. **No `order.send` capability exists**, so "place an order" is refused.
- Contract: HMAC-SHA256 signed, expiring. Each step checks its capability (`data.read`, `llm.call`,
  `memory.read`, `memory.write`); drafting runs under a child contract scoped to `action.draft` with
  `pharmacist-confirm`.
- Evidence: `tests/test_engine_scout_intent.py`, including Meterless's own adversarial injection set
  (`tests/fixtures/scout_injection_adversarial.jsonl`) scored against the precision/recall floors, plus our own
  StockWhy set. Examples `07_blocked_injection`, `08_refused_order`, `09_clarify_missing_month`.

**H-MEM** (`engines/hmem.py`)
- Case memory: each verified finding is stored with provenance (run id, cited rows) as `pending_approval`.
  The orchestrator recalls a facility's history before investigating and puts the remembered cause in wave 1
  (example `05_memory_recall`).
- Pharmacist feedback: approve → `helpful` (+0.05), reject → `wrong` (−0.20, review tag). Append-only ledger
  next to the memory file.
- Evidence: `tests/test_engine_hmem.py` runs the official conformance vectors (`tests/fixtures/hmem_vectors.json`).

## Meterless Nightshift: the primary AI provider

- `llm_client.py` follows the provider contract: `METERLESS_BASE_URL` (default `http://127.0.0.1:8088/v1`),
  Bearer runtime token, `meterless-app: stockwhy`, `meterless-scope: user`, deep and fast lanes, 180 s timeout.
- It is the only LLM path. It never switches provider silently; if a call fails, the agent uses its rule-based
  reasoning and records `_fallback_reason`.
- Evidence: `tests/test_llm_client.py` runs the client against a local fake server that follows the same contract.

## NVIDIA Nemotron: through Nightshift

- The NVIDIA key lives in Nightshift (Providers), never in this repo. Pin Nemotron routes for the lanes, e.g.
  `nvidia/nemotron-3.5-super-vl-120b-a12b` (deep) and `nvidia/nemotron-3.5-lightning-30b-a3b` (fast).
- Nemotron reasons before answering; an empty answer (`content: null`, `finish_reason: length`) is retried once
  with double the token budget, and the reasoning length is logged. 429/5xx back off; a run makes at most
  `STOCKWHY_MAX_LLM_CALLS` calls.
- **Which model answered** is recorded on every agent output (`_served_model`, `_produced_by`) and in each trace
  line's `model` field.
