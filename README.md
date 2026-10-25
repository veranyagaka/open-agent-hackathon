# StockyWhy

**A four-agent system that explains why a Kenyan health facility ran out of an essential medicine and drafts corrective actions for a pharmacist to approve.**

Built for the [Open Agent Hackathon 2026](https://genai.works) (Track: "The Agent That Can Explain Why").

> ⚠️ **Medical disclaimer:** This system provides decision-support information only. It does not constitute medical advice. No order, transfer, requisition, or payment will execute without explicit pharmacist approval.

> ⚠️ **Synthetic data:** All data in `data/` is synthetically generated. It does not represent real patient or facility records.

---

## What it does

Given a question like *"Why did Facility FAC-011 run out of ORS sachets in March 2026?"*, StockyWhy:

1. **Loads and profiles** the CSV data for that facility/commodity/month
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

### 2. API key

Copy `.env.example` to `.env` and fill in your Groq API key:

```bash
cp .env.example .env
```

Edit `.env`:

```
GROQ_API_KEY=gsk_your_key_here
GROQ_MODEL=openai/gpt-oss-120b
SAMPLE_MODE=false
```

Get a free Groq API key at: https://console.groq.com/keys

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

### Investigate a specific case

```bash
python run.py \
  --dataset data/cases/normal/case_01 \
  --facility FAC-011 \
  --commodity "ORS sachet" \
  --month 2026-03
```

### Use a case from questions.csv directly

```bash
python run.py --case data/cases/normal/case_01
```

### Sample mode (no API key needed for data loading)

```bash
SAMPLE_MODE=true python run.py \
  --facility FAC-011 \
  --commodity "ORS sachet" \
  --month 2026-03
```

> `SAMPLE_MODE=true` automatically uses `data/sample/`. An API key is still needed for the LLM steps.

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

Sample inputs and their outputs are in `output_examples/`:

- `output_examples/case_01_result.json` — demand surge
- `output_examples/case_03_result.json` — expiry + supplier underfill
- `output_examples/case_06_result.json` — late order

---

## Running tests

```bash
# Install pytest if not present
pip install pytest==8.3.5

# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_data_loader.py -v
```

**Test coverage** (88 tests):

| File | Tests | What it covers |
|------|-------|----------------|
| `tests/test_data_loader.py` | 44 | All 7 hypothesis checks, load_dataset, profile_stockout, known-case integration |
| `tests/test_logger.py` | 7 | JSONL format, appending, required fields, timestamps |
| `tests/test_agents.py` | 19 | All four agents with LLM mocked, parallel investigation, error handling |
| `tests/test_orchestrator.py` | 18 | Full pipeline, log files, SAMPLE_MODE, graceful failures, CLI args |

All tests use mocked LLM calls (no API key required). No test reads `eval/answer_key.csv`.

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
llm_client.py             ← Groq API wrapper
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

---

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `GROQ_API_KEY` | Groq API key | — (required) |
| `GROQ_MODEL` | Model name | `openai/gpt-oss-120b` |
| `SAMPLE_MODE` | Use `data/sample/` automatically | `false` |

---

## Models and frameworks

- **LLM**: Groq API (`openai/gpt-oss-120b` or any Groq-compatible model)
- **Data processing**: pandas, numpy
- **HTTP server**: stdlib `http.server`
- **Testing**: pytest (no external services)
- **AI coding tool**: Kiro (by AWS), Claude Sonnet

---

## Limitations

- All data is synthetic. Thresholds (e.g. 25% demand surge, 30M KES arrears) are illustrative, not calibrated to real Kenyan pharmacy data.
- The system cannot query live DHIS2, KEMSA, or county health systems.
- Web notes (`web_notes.json`) are synthetic placeholders for real public notices.
- The LLM may hallucinate reasoning text — evidence citations are grounded in actual row IDs but explanations should be verified.
- Rate limits on Groq may cause retries on parallel calls.

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
