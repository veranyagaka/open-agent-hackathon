# StockWhy

**A team of agents that explains why a Kenyan health facility ran out of an essential medicine, checks its own
evidence, and drafts corrective actions for a pharmacist to approve.**

Built by team NexusForge for the [Open Agent Hackathon 2026](https://genai.works), track "The Agent That Can
Explain Why".

> ⚠️ **Medical disclaimer:** decision support only, not medical advice. No order, transfer, requisition or payment
> is ever executed: the agents can only draft actions, and every action needs pharmacist approval.

> ⚠️ **Synthetic data:** everything in `data/` is synthetic. It does not describe real patients or facilities.

---

## Quick start (offline, no keys)

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # add -r requirements-dev.txt to run the tests

export SAMPLE_MODE=true            # PowerShell: $env:SAMPLE_MODE="true"
python run.py --question "Why did FAC-009 run out of magnesium sulphate in March 2026?"
```

`SAMPLE_MODE=true` runs the **whole** agent with no Zetaris, no Nightshift and no credentials: the data comes
from `data/sample/` and every agent uses its rule-based reasoning (it always switches the LLM off). Nothing is
replayed from saved outputs. Set it once per shell; the commands below assume it. If `SAMPLE_MODE` is unset and
no `METERLESS_RUNTIME_TOKEN` is configured, `run.py` falls back to sample mode by itself and prints one notice.
Questions may also be asked in Swahili month names, e.g. *"Kwa nini FAC-009 iliishiwa na magnesium sulphate
mwezi Machi 2026?"*.

---

## What it does

Given *"Why did FAC-009 run out of magnesium sulphate in March 2026?"*, StockWhy:

1. **Scout Intent** (Meterless engine) screens the request: blocks prompt injection, refuses out-of-scope asks
   (placing orders, dosing advice), asks for clarification when the facility, medicine or month is missing or
   not in the data, and otherwise issues a signed, expiring capability contract.
2. **H-MEM case memory** (Meterless engine) recalls earlier findings for that facility and medicine, so a known
   cause is investigated first.
3. **Data Reader** loads the data (from Zetaris in live mode) and computes the evidence for seven hypotheses with
   pandas. Agents explain; they never do the arithmetic.
4. **Data Analyst** and **Theory Generator** turn the signals into seven theories.
5. **Evidence Investigators** run in waves: the hypotheses with signals or memory priority first, the rest only
   if needed.
6. **Evaluator** re-reads every cited row and checks the numbers, checks each verdict against the computed flags,
   and critiques hypotheses against each other. A failed investigator is sent back **once** with the critique;
   a claim that still fails is dropped. If nothing is supported, a second wave runs; if still nothing, the case
   is **escalated to the pharmacist** rather than inventing a cause.
7. **Action Strategist** drafts actions under a narrower child contract (`action.draft`; no `order.send`
   capability exists).
8. The finding is stored in memory as `pending_approval`; the pharmacist's accept or reject updates its trust.

Every step is written to a JSONL trace in `logs/`.

### Seven hypotheses

| ID | Name | Check |
|----|------|-------|
| H1 | late_order | Previous month's order placed after cutoff, or delivery slipped past the stock-out month |
| H2 | supplier_underfill | Facility fill rate vs county average in the same cycle |
| H3 | payment_arrears | County owes ≥ 30M KES and county-wide fill of the supply arriving this month dropped |
| H4 | demand_surge | Consumption > 25% above the 3-month average |
| H5 | record_error | Stock identity (opening − wastage + received − consumed = closing) broken, or impossible stock-out days |
| H6 | expiry | Wastage > 2× its average and > 10% of average consumption |
| H7 | national_disruption | Public notice for the medicine and a county-wide drop in the supply arriving this month |

When several causes are supported, the root cause leads: national disruption, then arrears, record error,
expiry, late order, demand surge, and supplier underfill last (it is the symptom most other causes produce).

---

## Running

```bash
# A plain-English question (facility, medicine and month are matched to the data)
python run.py --question "Why did FAC-009 run out of magnesium sulphate in March 2026?"

# Explicit fields, on one of the 16 planted cases
python run.py --dataset data/cases/normal/case_01 --facility FAC-011 --commodity "ORS sachet" --month 2026-03

# A case folder (facility, medicine and month come from data/cases/questions.csv)
python run.py --case data/cases/normal/case_05

# JSON in, JSON out (no prompts, nothing but JSON on stdout)
python run.py --input input_examples/02_demand_surge.json --json

# Save the full result
python run.py --case data/cases/normal/case_01 --no-review --output results/case_01.json

# Fault drill for the demo: corrupt one cited value; the Evaluator catches it and the retry recovers
STOCKWHY_INJECT_FAULT=H1 python run.py --question "Why did FAC-009 run out of magnesium sulphate in March 2026?"

python run.py help
```

The interactive pharmacist review (accept / edit / reject each action) runs only in a terminal; with `--json`,
`--no-review`, `--input` or over HTTP the run never waits for input. Exit code is 1 only for a system or data
error; a blocked, refused or clarify result is a normal answer. If a question and explicit fields disagree
(e.g. the question says FAC-009 and `--facility` says FAC-011), StockWhy asks which one you mean.

### Web page and HTTP API

```bash
python run.py --serve                          # http://localhost:8000, this machine only
python run.py --serve --port 8080              # another port
python run.py --serve --host 0.0.0.0           # reachable from the network (no login: trusted networks only)
```

| Method | Path | |
|---|---|---|
| GET | `/` | Web page (`index.html`) |
| POST | `/run` | Same JSON as `--input`: `{"question"}` or `{"facility_id","commodity","month"}`, optional `"dataset"` (a folder under `data/`), `"role"` |
| POST | `/api/review` | Pharmacist decision on a stored finding: `{"memory_id", "decision": "approved"\|"rejected"\|"partial", "note"?, "action_decisions"?: {"A1": "accepted"\|"rejected"}}` → `{"ok", "memory_id", "status"}`. `memory_id` is `result.memory.stored_id`. The page's *Approve finding* / *Reject finding* buttons call it. |
| GET | `/api/facilities`, `/api/commodities`, `/api/cases` | Lists for the page |
| GET | `/health` | Liveness (`{"status": "ok", "service": "stockwhy"}`) |

The server is threaded, binds to 127.0.0.1 by default, caps request bodies at 64 KB, times out idle clients after
30 s, and rejects any `dataset` that does not resolve inside `data/`.

```bash
curl -X POST http://localhost:8000/run -H "Content-Type: application/json" \
  -d '{"question": "Why did FAC-011 run out of ORS in March 2026?", "dataset": "data/cases/normal/case_01"}'
```

---

## Sample inputs and outputs

`input_examples/` holds nine requests; `output_examples/` holds the matching results, regenerated with
`python scripts/make_examples.py` (sample mode, rule-based):

| Input | Shows | Result |
|---|---|---|
| `01_late_order_question.json` | Plain-English question on the demo county | late_order, `orders#1265` |
| `02_demand_surge.json` | Planted case | demand_surge, `stock#1506` |
| `03_national_disruption.json` | Planted case (CSV): a public notice plus a county-wide drop in supply arriving | national_disruption |
| `04_noisy_payment_arrears.json` | Noisy data, two supported causes | payment_arrears leads supplier_underfill |
| `05_memory_recall.json` | H-MEM recalls the finding from 01 and investigates H1 first | late_order |
| `06_fault_drill.json` | Evaluator catches a corrupted citation; investigator retries | caught and recovered |
| `07_blocked_injection.json` | Scout guard | block |
| `08_refused_order.json` | No `order.send` capability | refuse |
| `09_clarify_missing_month.json` | Scout asks for the month | clarify |

---

## Live mode: Zetaris + Meterless Nightshift

Copy `.env.example` to `.env` and fill it in (never commit `.env`).

**Zetaris (data layer).** Run Zetaris locally in Docker, then:

```bash
docker compose up -d                       # stockwhy-pg Postgres on Zetaris's network, seeded from data/sample
python scripts/setup_live.py --skip-load   # registers datasources stockwhy_pg and stockwhy_web, verifies a federated join
STOCKWHY_DATA_SOURCE=zetaris python run.py --question "Why did FAC-009 run out of magnesium sulphate in March 2026?"
```

Zetaris holds one registered dataset, the demo county in `data/sample`. Any other `--dataset` folder is read from
its CSV files and the run records a warning. Facility ids, months and medicine names are validated before they
reach SQL, one statement per call. Details: `ZETARIS_INTEGRATION.md`.

**Meterless Nightshift (AI provider).** Start Nightshift, copy its runtime token into `.env`
(`METERLESS_RUNTIME_TOKEN`), and pin Nemotron routes in Nightshift for the deep and fast lanes. With
`SAMPLE_MODE` unset (or `STOCKWHY_USE_LLM=true`) the agents call Nightshift; the trace records the model that
served each call (`model` / `_served_model`, or `unreported` when Nightshift does not say) next to the lane
requested (`requested_model`), plus any `meterless-*` / `x-*` routing headers. `<think>` blocks are stripped
before the JSON answer is read. Empty Nemotron answers are retried once with a larger budget, 429/5xx back
off, one call gives up after `STOCKWHY_LLM_DEADLINE_S` (default 300 s), and a run makes at most
`STOCKWHY_MAX_LLM_CALLS` (default 30) calls; the cap resets at the start of every run. Nightshift is never silently replaced
by another provider; if a call fails the agent falls back to its rule-based reasoning and says so.

---

## Architecture

```
run.py                       CLI, --input/--json, HTTP server (index.html, /run, /api/review, /api/*)
orchestrator.py              the loop: Scout → memory → agents → Evaluator → retry/second wave → strategist
  engines/scout_intent.py    Meterless Scout Intent: guard, binding, signed contracts
  engines/hmem.py            Meterless H-MEM: case memory, feedback, append-only ledger
  agents/data_reader.py      loads + profiles data
    tools/data_loader.py     deterministic evidence for H1–H7; CSV or Zetaris
  agents/data_analyst.py     interprets the signals
  agents/theory_generator.py seven theories
  agents/evidence_investigator.py  parallel investigation
  agents/evaluator.py        citation re-check, consistency, cross-critique, coverage
  agents/action_strategist.py      ranks causes, drafts actions
  agents/rules.py            shared deterministic verdicts and root-cause ranking
llm_client.py                Meterless Nightshift client (lanes, retries, call cap, model logging)
logger.py                    JSONL traces
scripts/trace_view.py        one readable line per trace event: agent, handoff, model, confidence, retries
scripts/                     setup_live, check_zetaris, evaluate, make_examples
```

### Traces

Every run writes `logs/run_<id>_<time>.jsonl`. Each line has `timestamp, run_id, agent_name, action,
input_summary, output_summary, target_agent, model, confidence, retry_count, status`. Actions include
`scout_gate, memory_recall, read_and_profile, plan_waves, investigate_wave, verify_citations, check_consistency,
cross_critique, request_revision, retry_investigation, accept_revision, drop_unverified, coverage_check,
request_second_pass, escalate_to_pharmacist, child_contract, recommend_actions, memory_store, memory_feedback,
contract_summary, pipeline_complete`. LLM steps also record `requested_model` and `served_model`. The same trace
is returned in the result as `trace`. To read one:

```bash
python scripts/trace_view.py                       # latest run
python scripts/trace_view.py --only evaluator,scout
```

---

## Tests and evaluation

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests          # no network, no keys
python scripts/evaluate.py         # back-test on the 16 planted cases → eval/RESULTS.md
```

| File | Tests | Covers |
|---|---|---|
| `test_data_loader.py` | 51 | H1–H7 checks, loading, known cases |
| `test_zetaris_loader.py` | 25 | Zetaris path against an in-memory stand-in: CSV/Zetaris parity, SQL validation, notices fallback |
| `test_agents.py` | 42 | every agent online (mocked) and rule-based |
| `test_llm_client.py` | 34 | Nightshift contract against a local fake server: lanes, empty-answer retry, 429 backoff, call cap, `<think>` stripping, model reporting, URL normalisation, deadline |
| `test_evaluator.py` | 20 | citation re-check, consistency, cross-critique, coverage |
| `test_orchestrator.py` | 33 | the loop, retries, waves, escalation, Scout and memory wiring, CLI |
| `test_engine_scout_intent.py` | 34 | guard on Meterless's adversarial set (precision/recall floors) and our own; contracts |
| `test_engine_hmem.py` | 25 | official H-MEM conformance vectors; memory round trip, dataset namespace, upsert, partial feedback, two writers, corrupt file |
| `test_logger.py` | 10 | trace fields, requested/served model |
| `test_run.py` | 14 | question parsing (Swahili, conflicts), `--case`, HTTP server hardening, `/api/review`, UTF-8 output |
| `test_zetaris_client.py` | 5 | Zetaris row shapes (headerless, upper-case), optional facility columns, timeout and 5xx retry |

Back-test (offline, rule-based): **15 of 16** planted cases get the right primary cause (8/8 normal, 7/8 noisy).
The rules were written while looking at these same cases, so treat this as a regression check, not proof of
accuracy on real data. Only `scripts/evaluate.py` reads `eval/answer_key.csv`; the agent never does.

---

## Configuration

| Variable | Default | |
|---|---|---|
| `SAMPLE_MODE` | unset | `true`: offline, CSV data, rule-based agents (always switches the LLM off) |
| `STOCKWHY_DATA_SOURCE` | `csv` | `zetaris` to read the demo county through Zetaris |
| `STOCKWHY_USE_LLM` | on unless `SAMPLE_MODE` | force the LLM on or off (`SAMPLE_MODE=true` still wins) |
| `METERLESS_BASE_URL` | `http://127.0.0.1:8088/v1` | Nightshift runtime (`/v1` is added if missing) |
| `METERLESS_RUNTIME_TOKEN` | | Nightshift runtime token |
| `METERLESS_MODEL_DEEP` / `METERLESS_MODEL_FAST` | `meterless/deep` / `meterless/fast` | lanes |
| `METERLESS_MODEL` | | fallback for the deep lane when `METERLESS_MODEL_DEEP` is unset |
| `STOCKWHY_MAX_LLM_CALLS` | `30` | per-run cap |
| `STOCKWHY_LLM_TIMEOUT_S` | `180` | one HTTP request to Nightshift |
| `STOCKWHY_LLM_DEADLINE_S` | `300` | one agent call, retries and backoff included |
| `STOCKWHY_LLM_MAX_TOKENS` | `4096` | answer budget (doubled once on an empty answer) |
| `STOCKWHY_LLM_BACKOFF_S` | `2` | base backoff for 429/5xx |
| `ZETARIS_REST_URL`, `ZETARIS_API_KEY`, `ZETARIS_ORG_ID` | | Zetaris REST |
| `ZETARIS_SCHEMA` / `ZETARIS_WEB_SCHEMA` | `stockwhy_pg` / `stockwhy_web` | Zetaris datasource names |
| `ZETARIS_TIMEOUT_S` | `120` | one Zetaris request (5xx or reset retried once) |
| `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_DATABASE`, `PG_WEB_DATABASE`, `PG_JDBC_PARAMS` | | Postgres for `scripts/setup_live.py` |
| `PG_ZETARIS_HOST` / `PG_ZETARIS_PORT` | `PG_HOST` / `5432` when the host is set | the Postgres address as Zetaris sees it |
| `STOCKWHY_LOGS_DIR` | `<repo>/logs` | trace folder |
| `STOCKWHY_MEMORY_PATH` | `<repo>/logs/memory/hmem.json` | case memory file |
| `SCOUT_SIGNING_KEY` | random per process | key that signs Scout contracts; set it only to keep contracts valid across processes |
| `STOCKWHY_INJECT_FAULT` | | fault drill (`H1`…`H7`) |

---

## Models, frameworks and tools

- **AI provider:** Meterless Nightshift (OpenAI-compatible runtime), NVIDIA Nemotron routes pinned in Nightshift.
  The NVIDIA key lives in Nightshift, never in this repo.
- **Meterless engines:** Scout Intent and H-MEM, implemented in Python from the specs at
  https://github.com/meterless/meterless; their conformance fixtures are in `tests/fixtures/` (Apache-2.0).
- **Data layer:** Zetaris (local Docker) over PostgreSQL 16.
- **Python:** pandas, numpy, python-dotenv; stdlib `http.server`; pytest.
- **AI coding tools:** Kiro, Cursor and Claude (Claude Code).
- Sponsor details: `SPONSORS.md`.

## Pre-existing components (declared)

- Commits before the build window: `b2bebb7` (14 Oct 2026), `287305b` and `7233d97` (20 Oct 2026).
- The synthetic datapack in `data/` was prepared around 22 Oct 2026.
- Meterless test fixtures in `tests/fixtures/` (third-party, Apache-2.0).

## Limitations

- All data is synthetic; thresholds (25% surge, 30M KES arrears, 5% underfill) are illustrative.
- Zetaris holds one dataset (the demo county); the planted cases are read from CSV.
- Public notices are synthetic placeholders for real KEMSA or ministry notices.
- With the LLM on, explanation text can still be wrong; verdicts come from computed flags and every cited row is
  re-checked by the Evaluator, but read the reasoning critically.
- No connection to live DHIS2, KHIS or KEMSA systems.
