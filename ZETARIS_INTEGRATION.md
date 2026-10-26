# Zetaris data layer

StockWhy reads its data through Zetaris in live mode. Judges and tests run offline in csv mode
(`SAMPLE_MODE=true`, or `STOCKWHY_DATA_SOURCE=csv`, the default).

## What Zetaris holds

Zetaris holds **one** registered dataset: `data/sample`, the demo county (30 facilities, 6 medicines,
24 months). It sits in two Postgres databases, registered as two Zetaris datasources:

| Datasource | Postgres database | Tables | Seeded from |
|---|---|---|---|
| `stockwhy_pg` | `stockwhy` | `stock`, `orders`, `payments`, `facilities` | `data/sample/postgres_load.sql` |
| `stockwhy_web` | `stockwhy_web` | `web_notes` (public notices) | `data/sample/web_notes_load.sql` |

The national-disruption check (H7) uses evidence from both, so a live run reads two federated sources.

## How `load_dataset` picks a source

```python
load_dataset(dataset_dir, source=None, facility_id=None, commodity=None, month=None)
```

- `source=None` means: `csv` if `SAMPLE_MODE=true`, otherwise `STOCKWHY_DATA_SOURCE` (default `csv`).
- `zetaris` with `dataset_dir` = `data/sample` reads the tables from `stockwhy_pg` and the notices from
  `stockwhy_web`. If `stockwhy_web` cannot be read, the notices come from `data/sample/web_notes.json`
  and a warning is recorded.
- `zetaris` with any other folder (the `data/cases/...` evaluation cases): the folder is honoured.
  With the source taken from the environment it is read from CSV and a warning is recorded. With
  `source="zetaris"` passed explicitly it raises `ValueError`.
- The result records what was used:
  - `dataset["_source"]`: `"zetaris:stockwhy_pg"` or `"csv:<dir>"` (for example `"csv:data/sample"`)
  - `dataset["_web_notes_source"]`: `"zetaris:stockwhy_web"`, `"csv:<dir>/web_notes.json"` or `"none"`
  - `dataset["_warnings"]`: list of strings (fallbacks)
  - `dataset["_queries"]` (Zetaris only): `{"sql", "rows", "ms"}` per call, for the trace. No secrets.

`profile_stockout` gives the same result from either source (tested in `tests/test_zetaris_loader.py`,
and checked live on `data/sample`, FAC-009, magnesium sulphate inj, 2026-03).

## Queries

- One SQL statement per REST call (`POST /sql-editor/sqls/run`, client in `scripts/check_zetaris.py`).
- Full reads take one call per table: 5,000 rows a page (stock and orders have 4,320 rows). The old
  100-row paging needed about 90 calls.
- Passing `facility_id`, `commodity` and `month` pushes filters into SQL, reading only what
  `profile_stockout` uses: stock `WHERE facility_id = ... AND commodity = ...`; orders
  `WHERE commodity = ... AND month IN (previous month, month)` (the county average needs every facility
  in that cycle); payments and facilities in full (county-wide, and returned in the profile).
- Literals are validated before they reach SQL: facility `FAC-\d{3}`, month `YYYY-MM`, commodity a
  restricted character set and present in `SELECT DISTINCT commodity FROM stockwhy_pg.stock` (an unknown
  commodity returns empty slices, as the CSV path does). Schema names come from `ZETARIS_SCHEMA` /
  `ZETARIS_WEB_SCHEMA` and must be plain identifiers.
- Values arrive as strings in `{"headers": [...], "data": [[...]]}`; the loader converts them with the
  same coercions as the CSV path.

Measured on a local install (Mac, Docker, 26 Oct): full read 4.8 s (5 calls), scoped read 3.7 s
(6 calls), CSV 0.3 s.

## Set up a local Zetaris (once)

1. Start Zetaris (its `docker compose`, then its `./verify.sh`). It creates the Docker network
   `zetaris_default`.
2. Copy `.env.example` to `.env` and fill in `ZETARIS_API_KEY` (Zetaris: Management > API Tokens) and
   `PG_PASSWORD` (any long random string). Keep `PG_ZETARIS_HOST=stockwhy-pg`, `PG_ZETARIS_PORT=5432`.
3. Start the bundled Postgres. It joins `zetaris_default` and seeds both databases on first start:
   ```
   docker compose up -d
   ```
4. Register both datasources and verify counts and a federated join:
   ```
   python scripts/setup_live.py --skip-load
   ```
   Expected: stock 4320, orders 4320, payments 24, facilities 30, notices 2, federated join 2, and
   `stock#1` opening/consumed/closing = 900/377/523. `--verify-only` re-runs just the checks.
   Without Docker, point `PG_*` at your own Postgres and run `python scripts/setup_live.py` (needs `psql`).

Windows: `.gitattributes` keeps `*.sh` files with LF endings so `scripts/pg_init_web.sh` runs inside the
container. To reseed after changing the SQL: `docker compose down -v && docker compose up -d`.

## Run

```
python -m pytest -q tests          # always csv: tests/conftest.py forces it, Zetaris is mocked
python scripts/check_zetaris.py    # connectivity
STOCKWHY_DATA_SOURCE=zetaris python run.py --dataset data/sample --facility FAC-009 \
  --commodity "magnesium sulphate inj" --month 2026-03
```

PowerShell: `$env:STOCKWHY_DATA_SOURCE = "zetaris"` before `python run.py ...`.

Never commit `.env`, keys or passwords. `data/sample/zetaris_register.sql` holds placeholders only;
`scripts/setup_live.py` fills them in memory and never prints them.
