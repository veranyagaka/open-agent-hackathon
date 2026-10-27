# StockWhy

**A four-agent system that explains why a Kenyan health facility ran out of an essential medicine and drafts corrective actions for a pharmacist to approve.**

Built for the [Open Agent Hackathon 2026](https://genai.works) (Track: "The Agent That Can Explain Why").

> **Medical disclaimer:** Decision-support only. No order or payment executes without explicit pharmacist approval.
> **Synthetic data:** All data in `data/` is synthetically generated.

---

## What it does

Given a question like *"Why did Facility FAC-011 run out of ORS sachets in March 2026?"*, StockWhy:

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

## Reasoning model: "LLMs explain, data decides"

All arithmetic runs in `tools/data_loader.py` (pandas only — no LLM). Each hypothesis produces a boolean flag. `_deterministic_verdict()` in `evidence_investigator.py` converts those flags into `supported / weakened / inconclusive`. The LLM then receives the pre-decided verdict and explains *why*, citing actual row IDs. If the LLM disagrees, its verdict is discarded:

```python
result["verdict"] = deterministic  # always overwrites the LLM's verdict
result["verdict_source"] = "deterministic"
```

Seven LLM explanation calls run concurrently via `ThreadPoolExecutor(max_workers=7)`.

---

## Sponsor integrations

### Meterless Nightshift (LLM gateway)

All four agents call `ask_agent()` in `llm_client.py`, which POSTs to `{METERLESS_BASE_URL}/chat/completions` with Bearer auth and the headers `meterless-app: stockwhy` and `meterless-scope: user`. The requested model is `METERLESS_MODEL_DEEP` (default `meterless/auto`); Nightshift selects the actual model. The live run reported served model `nvidia/nemotron-3.5-bolt-e4b`. Temperature is fixed at `0.2`.

The response JSON in `choices[0].message.content` is repaired through a safe pipeline (strip fences → fix quotes/control chars → remove trailing commas → insert missing commas) before being parsed. Truncated responses fail explicitly — no fields are invented.

When `SAMPLE_MODE=true`, `ask_agent()` routes to a local deterministic provider; no Nightshift call is made.

### Zetaris (data source)

`load_zetaris_dataset()` in `tools/data_loader.py` queries four registered tables — `facilities`, `stock`, `orders`, `payments` — in the configured `ZETARIS_SCHEMA` (default `STOCKWHY_PG`) via the SQL Editor REST API.

- Uses explicit `SELECT col1, col2, ...` (not `SELECT *`) because Zetaris returns positional row arrays; column order must be known to map values correctly.
- `_zetaris_rows()` handles both object rows and positional arrays; mixed or malformed rows fail explicitly.
- Stock is scoped to the target facility/commodity + 7-month history. Orders stay county-wide for H2/H3 peer comparisons.
- Paginates in batches of 100 rows (safety cap: 1M rows).
- `web_notes.json` is always read locally — Zetaris cannot access local files.

**Live verification (FAC-019 / iron-folate tab / 2026-03):** `STOCKWHY_PG` returned 30 facilities, 4,320 stock rows, 4,320 order rows, 24 payment rows. Stock row 2730 (closing 0, 17 stockout days) was returned correctly. All five pipeline stages completed; Nightshift reported served model `nvidia/nemotron-3.5-bolt-e4b`.

### NVIDIA

No direct NVIDIA client or API key is used. NVIDIA Nemotron is accessed through Nightshift's model routing only.

---

## Setup

### 1. Python environment

Requires Python 3.11+.

```bash
python -m venv my_env
source my_env/bin/activate        # Windows: my_env\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
```

Key variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `SAMPLE_MODE` | Offline mode — no external calls | `false` |
| `METERLESS_BASE_URL` | Nightshift API base URL | required in live mode |
| `METERLESS_RUNTIME_TOKEN` | Nightshift Runtime token | required in live mode |
| `METERLESS_MODEL_DEEP` | Requested model route | `meterless/auto` |
| `STOCKWHY_DATA_SOURCE` | `csv` or `zetaris` | `csv` |
| `ZETARIS_REST_URL` | Zetaris REST API base URL | required for Zetaris mode |
| `ZETARIS_API_KEY` | Zetaris API key | required for Zetaris mode |
| `ZETARIS_ORG_ID` | Zetaris organization ID | required for Zetaris mode |
| `ZETARIS_SCHEMA` | Registered source schema | `STOCKWHY_PG` |

### 3. Data

```
data/
  sample/       Demo county — 30 facilities, 6 medicines, 24 months
  cases/
    normal/     8 cases at normal noise (case_01..case_08)
    noisy/      Same 8 cause types with higher noise
    questions.csv
```

---

## Running

**Offline (no credentials needed):**
```bash
SAMPLE_MODE=true python run.py --facility FAC-011 --commodity "ORS sachet" --month 2026-03 --no-review
```

**Live CSV + Nightshift:**
```bash
SAMPLE_MODE=false python run.py --dataset data/cases/normal/case_01 --facility FAC-011 --commodity "ORS sachet" --month 2026-03 --no-review
```

**Live Zetaris + Nightshift:**
```powershell
$env:SAMPLE_MODE = "false"
$env:STOCKWHY_DATA_SOURCE = "zetaris"
python run.py --dataset data/cases/noisy/case_01 --facility FAC-011 --commodity "ORS sachet" --month 2026-03 --no-review
```

**From questions.csv:**
```bash
python run.py --case data/cases/normal/case_01 --no-review
```

**Save output / HTTP server:**
```bash
python run.py --dataset data/cases/normal/case_01 --facility FAC-011 --commodity "ORS sachet" --month 2026-03 --no-review --output results/case_01.json
python run.py --serve    # POST to http://localhost:8000/run
```

---

## Example output

```
[4/5] Evidence Investigator — evaluating theories in parallel...
    ✓ Evaluations: weakened, weakened, weakened, supported, weakened, weakened, weakened

Most Likely Cause: Demand surge (H4) – consumption was 72% above the 3-month average

  Proposed Actions:
    A1 [CRITICAL] — Submit an emergency requisition for ORS sachets
    A2 [HIGH]     — Adjust buffer stock policy (+30% safety stock)
```

Sample outputs: `output_examples/case_01_result.json` (demand surge), `case_03_result.json` (expiry), `case_06_result.json` (late order).

---

## Architecture

```
run.py / orchestrator.py
  ├── agents/data_reader.py        ← loads + profiles data
  │       └── tools/data_loader.py ← deterministic hypothesis calculations (pandas)
  ├── agents/data_analyst.py       ← interprets computed signals via LLM
  ├── agents/theory_generator.py   ← generates 7 theories via LLM
  ├── agents/evidence_investigator.py  ← 7 parallel LLM explanation calls
  │       └── _deterministic_verdict() ← verdicts from flags, never from LLM
  └── agents/action_strategist.py  ← ranks causes, drafts actions via LLM
llm_client.py             ← Meterless Nightshift client + offline sample provider
tools/world_model.py      ← provenance-backed SQLite World Model
logger.py                 ← JSONL audit trail (logs/)
```

---

## Running tests

```bash
python -m pytest -q
```

Tests cover CSV loading, Zetaris mocks, Nightshift mocks, the offline pipeline, World Model, orchestration, and logging. No test requires credentials or reads `eval/answer_key.csv`.

---

## Limitations

- All data is synthetic. Thresholds are illustrative, not calibrated to real Kenyan pharmacy data.
- Web notes (`web_notes.json`) are synthetic placeholders for real public notices.
- LLM reasoning text may hallucinate — row ID citations are grounded in actual data but explanations should be verified.
- Live Nightshift availability and served model depend on the Runtime configuration; the reported model can vary.
