# StockWhy

**A four-agent system that explains why a Kenyan health facility ran out of an essential medicine and drafts corrective actions for a pharmacist to approve.**

Built for the [Open Agent Hackathon 2026](https://genai.works) (Track 2: "The Agent That Can Explain Why").

> ⚠️ **Medical disclaimer:** This system provides decision-support information only. It does not constitute medical advice. No order, transfer, requisition, or payment will execute without explicit pharmacist approval.

> ⚠️ **Synthetic data:** All data in `data/` is synthetically generated. It does not represent real patient or facility records.

---

## What it does

Given a question like *"Why did Facility FAC-011 run out of ORS sachets in March 2026?"*, StockyWhy:

1. **Loads and profiles** local CSV data or configured Zetaris tables
2. **Calculates evidence deterministically** for seven hypotheses (no LLM for arithmetic)
3. **Generates seven theories** — one per hypothesis — using an LLM
4. **Investigates each theory in parallel** using the computed evidence
5. **Ranks causes, explains confidence**, and drafts practical corrective actions
6. **Asks the pharmacist to review, edit, accept, or reject** each proposed action

---

## Seven hypotheses

| ID | Name | Check |
|----|------|-------|
| H1 | late_order | Previous month's order placed after cutoff? Delivery slipped? |
| H2 | supplier_underfill | Facility fill rate vs county average in same cycle |
| H3 | payment_arrears | County owed ≥30M KES + county-wide fill drop |
| H4 | demand_surge | Consumed >25% above 3-month average |
| H5 | record_error | Stock identity equation: opening − wastage + received − consumed = closing |
| H6 | expiry | Wastage >2× historical average AND >10% of avg consumption |
| H7 | national_disruption | County-wide fill drop + public notice for this commodity |

---

## Setup

### 1. Python environment

Requires Python 3.11+.

```bash
python -m venv my_env
source my_env/bin/activate        # Windows: my_env\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure data and AI

Copy `.env.example` to `.env`. The defaults point to the bundled sample data.
Do not put real credentials in `.env.example`.

```bash
cp .env.example .env
```

PowerShell (does not overwrite an existing `.env`):

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

For a credential-free end-to-end run, enable sample mode:

```powershell
$env:SAMPLE_MODE = "true"
python run.py --facility FAC-011 --commodity "ORS sachet" --month 2026-03 --no-review
```

Sample mode reads `data/sample/`, uses an explicit offline provider for all
agent stages, and makes no Zetaris or Nightshift calls. Its recommendations
are cautious, evidence-derived review proposals and still require pharmacist
approval. It is not evidence of live sponsor-service usage.

For live Meterless Nightshift, set `SAMPLE_MODE=false` and configure
`METERLESS_BASE_URL`, `METERLESS_RUNTIME_TOKEN`, and optionally
`METERLESS_MODEL_DEEP` in `.env`. To demonstrate NVIDIA usage, select a
Nemotron model that is available in Nightshift's Providers configuration;
never put an NVIDIA key in this project.

For a local CSV dataset, set `STOCKWHY_DATASET` or pass `--dataset`. Zetaris
mode additionally requires `ZETARIS_REST_URL`, `ZETARIS_API_KEY`, and
`ZETARIS_ORG_ID`; the four tables must already be registered in Zetaris and
`web_notes.json` must remain alongside the selected dataset.

### 3. Data

The `data/` directory contains synthetic case data:

```
data/
  sample/           Demo county — 30 facilities, 6 medicines, 24 months
  cases/
    normal/         8 cases at normal noise (case_01..case_08)
    noisy/          Same 8 cause types with higher noise
    questions.csv   Input questions for each case
```

The `data/datapack/` directory has the original pack (larger datasets, PostgreSQL scripts).

---

## Running

### Root causes fixed

- Failed run traces used an invalid dataset argument (`/nonexistent/path`);
  the application had no usable dataset default and ignored
  `STOCKWHY_DATASET`. The CLI now reads that setting, validates required files,
  and reports how to fix a missing/invalid dataset without substituting data.
- Zetaris returns positional row arrays in the documented REST contract. The
  loader previously required row objects or headers; it now issues explicit
  column selects and maps arrays to that known order, rejecting malformed
  widths and preserving object fields.
- `SAMPLE_MODE=true` previously selected local files but still attempted
  Nightshift, and a configured Zetaris source could override the local source.
  It now runs all pipeline stages through an explicit offline provider and
  always uses local CSV; results and logs identify this as non-sponsor usage.
- `--case` did not resolve case inputs from `questions.csv` when the directory
  existed, and the root `test_agent.py` made a live Nightshift call during
  pytest collection. Both behaviors are corrected.
- Nightshift's OpenAI-compatible response carries the generated JSON as text
  in `choices[0].message.content`; the parser previously only retried strict
  `json.loads` and exposed parser details on malformed content. It now handles
  fences/prose and parser-directed, syntax-only repairs for quotes, control
  characters, trailing commas, and missing delimiters. It rejects truncated
  JSON without filling it in and never includes model output or prompts in
  parser errors. Data Analyst responses are checked against the requested
  schema rather than supplemented with invented fields.
- The Data Reader now persists a queryable, idempotent World Model snapshot
  with stable IDs and source-row provenance. This is a project-specific
  Meterless World Model implementation and is covered by regression tests.

### Investigate a specific case

```bash
SAMPLE_MODE=false python run.py \
  --dataset data/cases/normal/case_01 \
  --facility FAC-011 \
  --commodity "ORS sachet" \
  --month 2026-03 \
  --no-review
```

PowerShell:

```powershell
$env:SAMPLE_MODE = "false"
python run.py --dataset data/cases/normal/case_01 --facility FAC-011 --commodity "ORS sachet" --month 2026-03 --no-review
```

### Use a case from questions.csv directly

```bash
python run.py --case data/cases/normal/case_01 --no-review
```

The case directory is matched to `data/cases/questions.csv` to resolve its
facility, commodity, and month. Live runs require Meterless credentials;
credential-free runs should use the offline sample mode below.

### Full offline sample mode

```bash
SAMPLE_MODE=true python run.py \
  --facility FAC-011 \
  --commodity "ORS sachet" \
  --month 2026-03 \
  --no-review
```

PowerShell:

```powershell
$env:SAMPLE_MODE = "true"
python run.py --facility FAC-011 --commodity "ORS sachet" --month 2026-03 --no-review
```

Sample mode automatically selects `data/sample/`, regardless of
`STOCKWHY_DATASET` or `STOCKWHY_DATA_SOURCE`. No API key is needed.

### Zetaris data source (live mode)

Configure Zetaris credentials and register the StockWhy tables according to
[ZETARIS_INTEGRATION.md](./ZETARIS_INTEGRATION.md), then run:

```powershell
$env:SAMPLE_MODE = "false"
$env:STOCKWHY_DATA_SOURCE = "zetaris"
python run.py --dataset data/cases/noisy/case_01 --facility FAC-011 --commodity "ORS sachet" --month 2026-03 --no-review
```

The loader queries only explicitly named columns and maps Zetaris positional
rows to those columns. `web_notes.json` is read locally; Zetaris cannot read a
file on this machine. `ZETARIS_SCHEMA` selects the registered source schema
(defaults to `STOCKWHY_PG`); investigation loads filter stock to the facility's
seven-month history and orders to the current/previous month for the requested
commodity while retaining the county-wide comparisons.

Live validation against the registered Zetaris source found:

- Accessible Lightning databases: `NY_TAXI` and `TPCDS_DB`.
- Registered StockWhy tables in `STOCKWHY_PG`: `facilities` (30 rows),
  `stock` (4,320), `orders` (4,320), and `payments` (24).
- Full Zetaris-to-Nightshift run completed for `FAC-019` / `iron-folate tab` /
  `2026-03`. Zetaris returned stock row 2730 (closing 0, 17 reported stockout
  days) and previous order 2729. All five agent stages completed through
  Meterless Nightshift; seven theories and seven investigations were produced.
  The served model reported by Nightshift was
  `nvidia/nemotron-3.5-bolt-e4b`.

The tables are the project's synthetic dataset registered with Zetaris, not
authentic facility or operational stock records. This live run proves the
integration path and query availability, not real-world data provenance.

### Skip pharmacist review (non-interactive / CI)

```bash
python run.py --dataset data/cases/normal/case_01 \
  --facility FAC-011 --commodity "ORS sachet" --month 2026-03 \
  --no-review
```

### Save full JSON output

```bash
python run.py --dataset data/cases/normal/case_01 \
  --facility FAC-011 --commodity "ORS sachet" --month 2026-03 \
  --no-review \
  --output results/case_01.json
```

### HTTP server mode

```bash
python run.py --serve    # Starts on port 8000
```

Then POST:

```bash
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "dataset": "data/cases/normal/case_01",
    "facility_id": "FAC-011",
    "commodity": "ORS sachet",
    "month": "2026-03"
  }'
```

### Help

```bash
python run.py help
python run.py --help
```

---

## Example output

Running case_01 (demand surge, FAC-011, ORS sachet, March 2026):

```
[4/5] Evidence Investigator — evaluating theories in parallel...
    ✓ Evaluations: weakened, weakened, weakened, supported, weakened, weakened, weakened

Most Likely Cause: Demand surge (H4) – consumption was 72% above the 3-month average

  Ranked Hypotheses:
    [HIGH  ] H4 demand_surge — supported
    [LOW   ] H1 late_order — weakened
    ...

  Proposed Actions:
    A1 [CRITICAL] — Submit an emergency requisition for ORS sachets
    A2 [HIGH]     — Adjust buffer stock policy (+30% safety stock)
    ...
```

Historical sample outputs are in `output_examples/`. They are not loaded at
runtime and do not represent the credential-free offline provider's output:

- `output_examples/case_01_result.json` — demand surge
- `output_examples/case_03_result.json` — expiry + supplier underfill
- `output_examples/case_06_result.json` — late order

---

## Running tests

```bash
# Run all tests
python -m pytest -q

# Run specific test file
python -m pytest -q tests/test_data_loader.py
```

Tests exercise local CSV loading, Zetaris request/result handling with mocks,
Nightshift behavior with mocks, the offline full pipeline, the World Model,
agent orchestration, and logging. No unit test requires credentials, Docker,
or live sponsor services. No test reads `eval/answer_key.csv`.

---

## Architecture

```
run.py                    ← CLI / HTTP entry point
orchestrator.py           ← Pipeline coordinator
  │
  ├── agents/data_reader.py        ← Loads + profiles data; LLM interprets
  │       └── tools/data_loader.py ← Deterministic 7-hypothesis calculations
  │
  ├── agents/data_analyst.py       ← Interprets computed evidence signals
  ├── agents/theory_generator.py   ← Generates 7 theories (one per hypothesis)
  ├── agents/evidence_investigator.py  ← Parallel evaluation of each theory
  │       └── _deterministic_verdict() ← Verdicts from computed flags, not LLM
  └── agents/action_strategist.py  ← Ranks causes, drafts actions

logger.py                 ← JSONL audit trail (logs/)
llm_client.py             ← Meterless Nightshift + explicit offline sample provider
tools/world_model.py      ← Provenance-backed, idempotent SQLite World Model
```

### Design principles

- **Deterministic calculations first**: All arithmetic (fill rates, consumption averages, stock identity) uses pandas. LLMs explain, not calculate.
- **Verdicts from data**: `evidence_investigator._deterministic_verdict()` assigns supported/weakened/inconclusive from computed flags. The LLM writes the reasoning.
- **Parallel investigation**: 7 LLM calls run concurrently via `ThreadPoolExecutor(max_workers=7)`.
- **Traceable evidence**: Every finding cites actual row IDs (e.g. `stock#1506`, `orders#1505`).
- **Human in the loop**: All proposed actions require pharmacist accept/edit/reject before any downstream action.

---

## Logs

Every run produces a JSONL trace in `logs/`. Each line is an event:

```json
{
  "timestamp": "2026-10-25T09:12:34+00:00",
  "run_id": "52739c1b",
  "agent_name": "evidence_investigator",
  "action": "investigate_parallel",
  "input_summary": "7 theories + computed_evidence",
  "output_summary": "verdicts: weakened, weakened, weakened, supported, ...",
  "status": "ok"
}
```

Successful and failed live Nightshift requests include nested `request_metadata`:
provider, requested/served model, sanitized endpoint, HTTP status, duration,
request outcome, correlation ID, and whether a request was attempted, a response
was received, and its model JSON parsed successfully. Investigator events are
also logged individually per hypothesis. Deterministic verdicts remain marked
as such; if an explanation falls back locally, its source is explicitly
`local_deterministic_fallback` and the event is a warning, not a successful
Nightshift response. Logs do not include credentials, prompts, authorization
headers, or full model responses.

Generated `run_*.jsonl`, the World Model SQLite database, and generated JSON
outputs are ignored by Git. The database contains records from the selected
dataset; protect it as local data if using non-synthetic inputs.

---

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `SAMPLE_MODE` | Use local CSV and offline agent responses; disable external calls | `false` |
| `STOCKWHY_DATASET` | Dataset directory when `--dataset` is omitted | unset |
| `STOCKWHY_DATA_SOURCE` | `csv` or `zetaris`; sample mode always uses CSV | `csv` |
| `STOCKWHY_WORLD_MODEL_DB` | Persistent World Model SQLite event store | `logs/stockwhy_world_model.sqlite3` |
| `METERLESS_BASE_URL` | Nightshift OpenAI-compatible API base URL | required in live mode |
| `METERLESS_RUNTIME_TOKEN` | Nightshift Runtime token | required in live mode |
| `METERLESS_MODEL_DEEP` | Requested Nightshift model route | `meterless/auto` |
| `ZETARIS_REST_URL` | Zetaris REST API base URL | required for Zetaris mode |
| `ZETARIS_API_KEY` | Zetaris API key | required for Zetaris mode |
| `ZETARIS_ORG_ID` | Zetaris numeric organization ID | required for Zetaris mode |

---

## Models and frameworks

- **Live LLM provider**: Meterless Nightshift (actual served model is recorded when returned by the Runtime)
- **Offline sample provider**: deterministic local agent responses; no sponsor model is called
- **NVIDIA**: optional Nemotron model routed through Nightshift; NVIDIA API credentials are not used by the app
- **Data processing**: pandas, numpy
- **World Model**: project-specific Python implementation using SQLite; source rows retain provenance
- **HTTP server**: stdlib `http.server`
- **Testing**: pytest (no external services)
- **AI coding tools**: VS Code Copilot SDK for the current maintenance task; Cursor rules are present in `.cursor/`

## Sponsor integration status

| Sponsor | Implementation and verification |
|---------|----------------------------------|
| Zetaris | SQL Editor REST client and loader implemented, mock-tested, and live-tested. `STOCKWHY_PG` has 30 facilities, 4,320 stock rows, 4,320 order rows, and 24 payment rows; a complete live investigation queried a confirmed stockout row. The records are synthetic project data. |
| Meterless | Nightshift client implemented, contract-tested, and live-tested end-to-end on the Zetaris stockout case. Malformed JSON is repaired only when syntax repair is unambiguous; incomplete output fails without mock substitution or invented fields. |
| NVIDIA | No direct NVIDIA client or key. The completed Nightshift run reported served model `nvidia/nemotron-3.5-bolt-e4b`; this verifies the routed model reported by Nightshift, not a direct NVIDIA integration. |
| Bright Data | No client or live fetch is implemented. Current `web_notes.json` data is synthetic/local. Integration is deferred because the project has no configured zone/credentials and the sponsor bounty is unconfirmed in `research/`. |

---

## Limitations

- All data is synthetic. Thresholds (e.g. 25% demand surge, 30M KES arrears) are illustrative, not calibrated to real Kenyan pharmacy data.
- The system cannot query live DHIS2, KEMSA, or county health systems.
- Web notes (`web_notes.json`) are synthetic placeholders for real public notices.
- The LLM may hallucinate reasoning text — evidence citations are grounded in actual row IDs but explanations should be verified.
- Live Nightshift availability, model entitlements, and NVIDIA routing depend on the teammate-managed Runtime and its configuration; the reported served model can vary by route and availability.
- The Python World Model implements the project’s entity/provenance snapshot workflow; it is not the Meterless TypeScript reference implementation or a full conformance-suite port.

---

## Evaluation

To measure accuracy against known cases without the agent seeing the answer key:

```bash
# Run the agent on each case (questions.csv has the inputs)
cat data/cases/questions.csv

# Compare agent output to eval/answer_key.csv manually
# Never point the agent at eval/answer_key.csv
```

The answer key has 16 cases (8 normal + 8 noisy). Ground truth causes: demand_surge, late_order, supplier_underfill, payment_arrears, record_error, expiry, national_disruption.
