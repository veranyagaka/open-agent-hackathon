# Data (synthetic records, real facility locations)

Stock, orders, payments and notices are generated test data. They are not real records of any facility, patient or supplier.
Facility names, types and locations are real: 30 public dispensaries, health centres and sub-county hospitals in Kitui County, taken from OpenStreetMap. The synthetic events attached to them (late orders, stock-outs) are invented and say nothing about how these facilities actually perform. Column meanings are in `DATA_DICTIONARY.md`, and the public sources we cite are in `PUBLIC_DATA_SOURCES.md`.

Facility data © OpenStreetMap contributors, available under the Open Database License (ODbL 1.0), via the HOT export on HDX (`hotosm_ken_health_facilities`). The facilities table is shared under the same licence.

How the facilities were chosen:
1. Take the OSM features tagged hospital, clinic or doctors in Kitui that are either tagged as public/government or named as a public facility type (dispensary, health centre, sub-county hospital).
2. Remove duplicates within 300 m.
3. Assign each FAC id to a distinct facility so that the original synthetic layout is kept as closely as possible: fixed scale, best rotation and shift, minimum total displacement.

The same FAC id is the same facility in every dataset.

| Path | What it is |
|---|---|
| `sample/` | Demo county: 30 facilities, 6 medicines, 24 months (`facilities.csv`, `stock.csv`, `orders.csv`, `payments.csv`, `web_notes.json`). Used by `SAMPLE_MODE=true`. FAC-009 and similar have a repeated late-ordering problem. |
| `sample/postgres_load.sql` | Creates and fills the 4 tables in Postgres. Zetaris reads the data from there. |
| `sample/zetaris_register.sql` | Registers that Postgres as a Zetaris datasource. Fill in the placeholders locally and never commit real values. |
| `cases/normal/case_01..08/` | Eight stock-outs, one per cause type, normal noise. Same file layout as `sample/`. |
| `cases/noisy/case_01..08/` | The same eight cause types with much messier data. |
| `cases/questions.csv` | The question for each case: `dataset`, `facility_id`, `commodity`, `month`, and `noise_level` (how messy that case's data is: 1.0 for the normal set, 2.5 for the noisy set). This is the agent's input. |

The true causes are in `../eval/answer_key.csv`. **The agent must never read that file.** Only the evaluation script
does.

Not in the repo: a larger 150-facility county (2.9 MB), kept by the team outside git.
