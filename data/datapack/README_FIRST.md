# StockWhy data pack (all data is SYNTHETIC)

Do not commit this whole pack to the GitHub repo (the hackathon wants a light repo). Share it with the team by zip, Drive or chat. Only `data_sample_for_repo/` is small enough to commit.

| Folder or file | What it is | Size |
|---|---|---|
| `01_demo_county_30/` | The demo county the UI uses (30 facilities, 6 medicines, 24 months). FAC-009 and similar have a repeated late-ordering problem | 4,320 stock rows |
| `02_big_county_150/` | A larger clean county with no planted problem, for bigger tests, charts and Zetaris loading | 21,600 stock rows |
| `03_cases_normal/case_01..08/` | Eight stock-outs, one per cause type, at normal data noise. Cases are shuffled and neutrally named | 4,320 rows each |
| `04_cases_noisy/case_01..08/` | The same eight cause types with much messier data (noise 2.5) | 4,320 rows each |
| `ANSWER_KEY.csv` | The true cause of every case. **Keep this away from the agent**: it must never read it | 16 rows |
| `01_demo_county_30/postgres_load.sql` | Paste into a Postgres SQL editor (for example Neon) to create and fill the 4 tables | 0.8 MB |
| `01_demo_county_30/zetaris_register.sql` | The Zetaris statements that register that Postgres as a source (fill in the placeholders) | small |
| `data_sample_for_repo/` | A small copy of the demo county that is fine to commit, e.g. as `data/sample/` | 0.8 MB |
| `DATA_DICTIONARY.md` | What every column means and which hypothesis uses which file | |
| `PUBLIC_DATA_SOURCES.md` | Real, freely available data you can use or cite | |

## Use a dataset without any script

Every dataset folder is plain CSV. Open it in Excel or Cursor. To run the agent on one:

```
python run.py --serve --dataset path/to/01_demo_county_30
python run.py --dataset path/to/03_cases_normal/case_01 --facility FAC-xxx --commodity "ORS sachet" --month 2026-03
```

Take the facility, medicine and month for each case from `ANSWER_KEY.csv`.

## Is it enough to "train" on?

The agents do not train on this data. The seven checks are rules over the tables, and the language model only explains evidence. Data is used to **test and tune**: the pack gives you 16 cases with known answers, in normal and messy conditions, so you can measure accuracy, find weaknesses and adjust thresholds. More rows do not help much; more *variety* and more *realistic messiness* do. Make as many extra datasets as you like by changing the seed (`python scripts/generate_data.py --seed 99 --plant-cause expiry --facilities 150`).
