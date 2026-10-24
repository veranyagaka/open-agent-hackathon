# Data (all SYNTHETIC)

Every file here is generated test data for StockWhy. No real facility, patient or supplier data. Column meanings are
in `DATA_DICTIONARY.md`; real public sources we can cite are in `PUBLIC_DATA_SOURCES.md`.

| Path | What it is |
|---|---|
| `sample/` | Demo county: 30 facilities, 6 medicines, 24 months (`facilities.csv`, `stock.csv`, `orders.csv`, `payments.csv`, `web_notes.json`). Used by `SAMPLE_MODE=true`. FAC-009 and similar have a repeated late-ordering problem. |
| `sample/postgres_load.sql` | Creates and fills the 4 tables in Postgres. Zetaris reads the data from there. |
| `sample/zetaris_register.sql` | Registers that Postgres as a Zetaris datasource. Fill in the placeholders locally and never commit real values. |
| `cases/normal/case_01..08/` | Eight stock-outs, one per cause type, normal noise. Same file layout as `sample/`. |
| `cases/noisy/case_01..08/` | The same eight cause types with much messier data. |
| `cases/questions.csv` | The question for each case: dataset, facility, medicine, month. This is the agent's input. |

The true causes are in `../eval/answer_key.csv`. **The agent must never read that file.** Only the evaluation script
does.

Not in the repo: a larger 150-facility county (2.9 MB), kept by the team outside git.
