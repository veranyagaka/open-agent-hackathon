# Zetaris + Meterless integration

## What changed
- `tools/data_loader.py` supports `STOCKWHY_DATA_SOURCE=csv` (default) and `zetaris`.
- Zetaris mode queries `STOCKWHY_PG.stock`, `orders`, `payments`, and `facilities` through the existing SQL Editor REST client.
- Table reads are paginated in batches of 100 to match the existing request limit.
- Existing numeric/date coercions are preserved, and `web_notes.json` is loaded from the selected local case directory.
- Added mocked tests in `tests/test_zetaris_loader.py`.
- `.env.example` documents required Meterless and Zetaris variables. Do not put real credentials in it.

## Configure locally (PowerShell)
Copy `.env.example` to `.env` only if you need a template; keep your existing `.env` and its working values.

Required variables:
- `METERLESS_BASE_URL`
- `METERLESS_RUNTIME_TOKEN`
- `METERLESS_MODEL_DEEP` (optional; defaults to `meterless/auto` if unset)
- `ZETARIS_REST_URL`
- `ZETARIS_API_KEY`
- `ZETARIS_ORG_ID`

## Run regression tests
```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m pytest -q tests
```

## Run end-to-end against Zetaris + Meterless
Run from the repository root. Use a local case directory that contains `web_notes.json` (the selected case directory is still needed for those notes):

```powershell
$env:STOCKWHY_DATA_SOURCE = "zetaris"
$env:PYTHONIOENCODING = "utf-8"
python run.py --dataset data/cases/noisy/case_01 --facility FAC-011 --commodity "ORS sachet" --month 2026-03 --no-review --output outputs/zetaris-run.json
```

The command uses the local case directory for `web_notes.json`; stock, orders, payments, and facilities are loaded from Zetaris. The run still calls Meterless through the existing `ask_agent` client. The CLI should print the final investigation summary and save the full result to `outputs/zetaris-run.json`.

## Switch back to CSV
```powershell
$env:STOCKWHY_DATA_SOURCE = "csv"
python run.py --dataset data/cases/noisy/case_01 --facility FAC-011 --commodity "ORS sachet" --month 2026-03 --no-review
```
