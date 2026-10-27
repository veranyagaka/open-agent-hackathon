# Zetaris, Meterless, and local sample integration

## Current implementation

- `tools/data_loader.py` supports `STOCKWHY_DATA_SOURCE=csv` (default) and
  `zetaris`. `SAMPLE_MODE=true` always selects the local sample CSV and offline
  agent provider, regardless of the configured data source.
- Zetaris mode queries the explicitly selected columns in the configured
  `ZETARIS_SCHEMA` (default `STOCKWHY_PG`) through the documented SQL Editor
  REST interface. Schema names are validated as simple SQL identifiers.
- Reads are paginated in batches of 100. Positional Zetaris rows are mapped to
  the explicit `SELECT` column order when response headers are absent; returned
  metadata is preferred when present. Malformed results and missing columns
  fail explicitly rather than discarding values.
- An investigation scopes stock to the selected facility/commodity and target
  month plus the previous six months. Orders remain county-wide for that
  commodity and the current/previous month, preserving peer comparisons.
- Numeric/date coercions are shared with CSV mode. `web_notes.json` is read
  locally from the selected dataset directory.
- Mocked tests cover request headers, missing configuration, successful
  responses, returned row formats, malformed data, and loader conversions.
- Meterless's OpenAI-compatible completion JSON is parsed from
  `choices[0].message.content`. Safe syntax-only fixes handle common generated
  JSON quoting/control-character/trailing-comma/missing-delimiter mistakes;
  truncated or incomplete responses fail explicitly without fabricating
  fields. Analyst output is schema-checked and parse errors do not expose
  prompt/response text.
- Unit tests mock Nightshift responses. A live investigation also completed
  through every stage on a Zetaris-backed stockout case.

## Live verification results

The Zetaris connection and SQL Editor query path were live-tested. Zetaris
listed `NY_TAXI` and `TPCDS_DB` as accessible Lightning databases. StockWhy's
registered source was the configured `STOCKWHY_PG` schema, where the
`facilities`, `stock`, `orders`, and `payments` tables returned 30, 4,320,
4,320, and 24 rows respectively.

The live case query returned this usable stock row:

```sql
SELECT id, facility_id, commodity, month, opening, received, wastage,
       consumed, closing, reported_stockout_days
FROM STOCKWHY_PG.stock
WHERE facility_id = 'FAC-019'
  AND commodity = 'iron-folate tab'
  AND month = '2026-03';
```

It returned stock row `2730` (closing `0`, reported stockout days `17`); the
previous-cycle order was `2729`. The full workflow completed Data Reader,
Data Analyst, Theory Generator, Evidence Investigator, and Action Strategist
using Meterless Nightshift, with seven theories, seven investigations, and two
proposed actions. Nightshift reported served model
`nvidia/nemotron-3.5-bolt-e4b`. The registered rows are synthetic project
records, so this verifies connectivity, registration, query execution, and
workflow integration—not access to authentic operational stock data.

## Configure locally (PowerShell)
Copy `.env.example` to `.env` only if you need a template; keep your existing `.env` and its working values.

Required variables:
- `METERLESS_BASE_URL`
- `METERLESS_RUNTIME_TOKEN`
- `METERLESS_MODEL_DEEP` (optional; defaults to `meterless/auto` if unset)
- `ZETARIS_REST_URL`
- `ZETARIS_API_KEY`
- `ZETARIS_ORG_ID`
- `ZETARIS_SCHEMA` (optional; defaults to `STOCKWHY_PG`)

Configure `STOCKWHY_DATASET` for the CSV directory used when `--dataset` is
omitted, and `STOCKWHY_DATA_SOURCE=zetaris` to read the registered Zetaris
tables. The local Zetaris API base normally includes `/api/v1.0`, for example
`http://localhost:8888/api/v1.0`. Keep all real values in the ignored `.env`;
never put them in `.env.example`.

## Run regression tests
```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m pytest -q tests
```

## Run end-to-end against Zetaris + Meterless
Run from the repository root. Use a local case directory that contains `web_notes.json` (the selected case directory is still needed for those notes):

```powershell
$env:SAMPLE_MODE = "false"
$env:STOCKWHY_DATA_SOURCE = "zetaris"
$env:PYTHONIOENCODING = "utf-8"
python run.py --dataset data/cases/noisy/case_01 --facility FAC-011 --commodity "ORS sachet" --month 2026-03 --no-review --output outputs/zetaris-run.json
```

The command uses the local case directory for `web_notes.json`; stock, orders,
payments, and facilities are loaded from Zetaris. Stock and order rows are
scoped to the case while keeping the county-level order comparison. The CLI
prints the final investigation summary and writes the full result to the
specified output path. The live validation above used the same flow against
the teammate-hosted Zetaris and Nightshift services.

## Switch back to CSV
```powershell
$env:SAMPLE_MODE = "false"
$env:STOCKWHY_DATA_SOURCE = "csv"
python run.py --dataset data/cases/noisy/case_01 --facility FAC-011 --commodity "ORS sachet" --month 2026-03 --no-review
```

For the full credential-free pipeline, see the `SAMPLE_MODE=true` command in
the [README](./README.md). Sample mode makes no external-service calls and is
not a live Zetaris or Meterless test.
