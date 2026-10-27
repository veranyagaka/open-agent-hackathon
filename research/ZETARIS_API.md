# Zetaris: everything needed for a Python client

Primary source: the official Zetaris onboarding repo **https://github.com/zetaris/getting-started** (commit `6a2fbaa`,
2026-10-22; its START-HERE.md links to the hackathon event page, so it is the hackathon onboarding material).
Its own Python client code is `scripts/zetaris_api.py`, `scripts/zetaris_sql.py`, `scripts/query_zetaris.py`,
`scripts/run_sql.py` and `scripts/preflight.py`, all standard library apart from optional `jaydebeapi` for JDBC.
Paths below are relative to that repo. Accessed 2026-10-23.

Anything HackOS may add on top of this (team instances, shared credentials): **NOT FOUND**, needs a logged-in pass.

## 1. How a team gets an instance

START-HERE.md: "Set up your own Zetaris instance using one of the routes below. If your computer meets the requirements, you can start local. Otherwise, install Zetaris on AWS."

| Route | Steps (source) |
|---|---|
| Local Docker | Register at https://cloud.enterprise.zetaris.com/register ("Start Free"). Download `zetaris-platform.zip` from https://cloud.enterprise.zetaris.com/dashboard/download, then `docker login zetarishackathon.azurecr.io`, `./preflight.sh`, edit `.env`, `docker compose pull`, `docker compose up -d`, `./verify.sh`, and open http://localhost:3000 (`docs/install/updated_zetaris_installation_guide.md`) |
| Managed AWS cluster | Zetaris Cloud Gateway: **Compute > Credentials > Add AWS Account > Quickstart**, region `us-west-1`, CloudFormation "Launch Stack", then **Compute > Clusters > Create Cluster**, size **Mini** ("two nodes and four vCPUs in total"). "Allow approximately **30 minutes** for provisioning." (`docs/install/managed-aws-cluster-guide.md`) |

Local requirements (`docs/install/choose-install.md`): Docker Engine 25+, "8 GB available **to Docker** recommended. The install's own preflight check fails below 6 GB.", 4 CPUs, 15 GB disk. "The Zetaris images are amd64. Apple Silicon runs them through emulation, which needs extra startup time." Time to first query: "About 20 to 30 minutes".

AWS costs: "In Zetaris testing a Mini cluster running non-stop for about a week used roughly $80 of them, so a five-day event fits within the credits" (new AWS Free Tier account, up to $200 in credits).

Licence: "Without one, the agreement allows internal evaluation for up to 30 days; it does not grant an ongoing licence." "at this size the Zetaris software is free in either place."

Shared event instance: `docs/plans/hackathon-user-journey.md` says "Shared event instance: confirmed. Require an assigned team prefix and permissions." The current START-HERE only describes your own instance. Whether HackOS hands out a shared instance is **NOT FOUND** (see OPEN_QUESTIONS.md).

Built-in samples after install: Lightning databases `NY_TAXI` and `TPCDS_DB` (`docs/connections/lightning-recipe-reference.md`).

## 2. Three ways to call it programmatically

| Channel | Base URL (local default) | Auth | Use |
|---|---|---|---|
| **Direct REST** | `ZETARIS_REST_URL=http://localhost:8888/api/v1.0` | `Authorization: Bearer <API key>` + `X-Org-ID` + `X-Request-ID` (UUID) | Recommended for our Python agent |
| UI proxy | `ZETARIS_BASE_URL=http://localhost:3000` (UI origin, no path) | Bearer API key, **or** `POST /api/auth/login` with username/password | Small helpers `query_zetaris.py`, `check_zetaris.py` |
| JDBC | `ZETARIS_JDBC_URL=jdbc:zetaris:lightning@localhost:10000` | username/password | Needs JDK 11+, the driver JAR, `jaydebeapi` |

client-setup.md: "The routes use separate addresses: put the API base in `ZETARIS_REST_URL` and the web UI origin in `ZETARIS_BASE_URL`." "For Zetaris Cloud or another remote instance, use the URLs supplied to you."

**MCP server:** zetaris.com mentions "MCP / REST" and links "Cursor_Connection_Guide" at
https://kbase.zetaris.com/knowledge/coding-agent-connection-guide-cursor, but that page's body did not render without
JavaScript. The getting-started repo's Cursor guide (`docs/connections/cursor-connection.md`) only uses JDBC/REST and
the repo scripts. A Zetaris MCP server URL or config: **NOT FOUND**.

**Python SDK:** zetaris.com lists "Python / Spark SDK". Package name and docs: **NOT FOUND**. Use plain HTTP (below).

## 3. Credentials (no secrets here)

Store them in `.env.local` (gitignored). Variable names are from `.env.example`:

```dotenv
ZETARIS_REST_URL=http://localhost:8888/api/v1.0
ZETARIS_BASE_URL=http://localhost:3000
ZETARIS_ORG_ID=            # numeric, from Management → Organisation → ID
ZETARIS_API_KEY=           # created in the GUI: Management → API Tokens → "+"
ZETARIS_USERNAME=          # needed for JDBC and for fetching the OpenAPI spec
ZETARIS_PASSWORD=
ZETARIS_ENGINE_ID=         # optional (UI proxy only)
ZETARIS_QUERY_LIMIT=1000   # UI proxy only
ZETARIS_JDBC_URL=jdbc:zetaris:lightning@localhost:10000
ZETARIS_JDBC_JAR=          # full path to the driver JAR; "ask where it lives, do not guess"
```

API key steps (client-setup.md "Create an API key"): "In the sidebar, open **Management → API Tokens**. Click the **+** button at the top right to create an API key." "Each key is shown in plaintext only once. The key has your account's permissions. Never ask an agent to create or fetch it". "If REST returns `401`, create a fresh key on this page".

Org ID: "Copy the numeric value in the **ID** field into `ZETARIS_ORG_ID`". "Use the **ID**, not the organisation name or login URL slug."

## 4. Direct REST: request and response

From `scripts/zetaris_sql.py` (`RestChannel`):

### Run SQL
```
POST {ZETARIS_REST_URL}/sql-editor/sqls/run
Authorization: Bearer <ZETARIS_API_KEY>
X-Org-ID: <ZETARIS_ORG_ID>
X-Request-ID: <uuid4>
Content-Type: application/json

{"queryId": "<uuid4>", "sql": "SELECT 1", "source": "SqlEditor", "limit": 100}
```
- Timeout used by Zetaris's runner: `urlopen(req, timeout=600)`.
- Response: a JSON object. The runner reads rows from `out.get("data")`. Preflight checks `SELECT 1` with `ch.run("SELECT 1").rows == [["1"]]`, so `data` is a **list of rows, each a list of values**.
- client-setup.md: "REST returns values as strings, and decimals may use exponent format; convert them before comparing."
- A full response JSON example (column names/metadata keys) is **NOT FOUND** in the repo. Fetch the OpenAPI spec (below) to confirm.

### List datasources
```
GET {ZETARIS_REST_URL}/datasource/datasources     (same headers)
```
The response is a list, or an object with `data`. Each item has `name` (from preflight.py: `ds if isinstance(ds, list) else ds.get("data", [])`, then `d.get("name")`).

### OpenAPI spec (the authoritative endpoint list)
```sh
curl -sS -u "$ZETARIS_USERNAME:$ZETARIS_PASSWORD" \
  "${ZETARIS_REST_URL%/api/v1.0}/redoc/docs.yaml" -o /tmp/zetaris-docs.yaml
```
"The spec route uses HTTP Basic authentication ... It does not accept the bearer API key." Local docs page: http://localhost:8888/redoc/index.html.

### Error meanings (client-setup.md troubleshooting)
| Symptom | Meaning |
|---|---|
| `401` | Bad or expired API key: create a new one |
| `400 Not Allowed` | `ZETARIS_ORG_ID` is not your numeric ID |
| `400` on a valid request | "Check that `X-Request-ID` and `queryId` are UUIDs." |
| 404 / HTML on the UI proxy | `ZETARIS_BASE_URL` is not the UI origin |

## 5. UI proxy: request and response

From `scripts/zetaris_api.py` and `scripts/query_zetaris.py`:

```
POST {ZETARIS_BASE_URL}/api/auth/login        # only if no API key
Content-Type: application/json
X-Request-ID: <uuid4>
{"username": "...", "password": "..."}
→ token taken from idToken | token | accessToken

POST {ZETARIS_BASE_URL}/api/proxy/sql-editor/sqls/run-query
Authorization: Bearer <token>
X-Org-ID: <org id>
X-Request-ID: <uuid4>
{"sql": "SELECT 1", "limit": 1000, "engineId": "<optional>"}

GET {ZETARIS_BASE_URL}/api/proxy/lightning-database/databases   → JSON list
```
Timeout 30 s. Response shape, from `examples/pudl-chart/render.py`: an object with a `data` array plus optional
`headers` (a list of strings or `{"name": ...}` objects). Rows may be objects (column → value) or arrays that line up
with `headers`. The renderer accepts both, so the exact form is not fixed.

## 6. Loading our data (CSV / Parquet / Postgres)

**Local files are not directly readable.** troubleshooting.md: "Put it in storage Zetaris can reach. A file on your laptop may be out of reach." Parquet/CSV HOWTO: "Zetaris cannot read this local cache by a documented `PATH`; move the file to reachable storage before registering it."

### Option A: Postgres datasource (what `data/sample/zetaris_register.sql` does)
Command reference §4.1 / §4.3 (`docs/guides/zetaris-lightning-sql-commands.md`):
```sql
CREATE DATASOURCE <name> [DESCRIBE BY '<desc>'] OPTIONS (key 'value', …)   -- "Administrators only."
REGISTER DATASOURCE TABLES [('<table>', …)] FROM <datasource>              -- all tables if no list
SHOW DATASOURCE TABLES <datasource>
DESCRIBE DATASOURCE TABLE <datasource>.<table>
```
Documented example options: `jdbcdriver "org.postgresql.Driver"`, `jdbcurl "jdbc:postgresql://host:5432/db"`, `username`, `password`, `fetchsize "1000"`. "Registers an external source (JDBC, Cassandra, MongoDB or DynamoDB, detected from the options) after testing the connection."

Our `data/sample/zetaris_register.sql` matches this syntax. The instance must be able to reach the Postgres host (for example Neon). INFERRED: a local Docker Zetaris can reach a cloud Postgres.

### Option B: CSV/Parquet on S3
```sql
CREATE LIGHTNING DATABASE <db> DESCRIBE BY "<short description>";
CREATE LIGHTNING FILESTORE TABLE <table> FROM <db> FORMAT CSV OPTIONS (
  PATH "s3a://bucket/prefix/file.csv", inferSchema "true", header "true",
  isS3BucketPublic "true", useS3PathStyleAccess "true", s3Endpoint "s3.<region>.amazonaws.com"
);
```
Private buckets use `awsAccessKeyId` / `awsSecretAccessKey` options (command reference §5.3). Supported formats: "CSV, JSON, PARQUET, ORC, DELTA, XML, AVRO, PDF, IMAGE, VIDEO, AUDIO, DOC, TEXT, MARKDOWN, RTF". Gotchas: "`DESCRIBE BY` accepts letters, digits, spaces, `_`, `.`, `-` and `,`. Parentheses, slashes and colons fail validation." and "Dotted bucket names fail here."

§5 also lists "platform storage" as a file location. How to upload into it: **NOT FOUND**.

### Option C: REST/JSON source (for example a live notices feed)
`CREATE LIGHTNING REST TABLE ...` then `CREATE SCHEMASTORE VIEW ... AS SELECT ... LATERAL VIEW explode(...)`. See `open_data/rest_apis/HOWTO.md` and `docs/guides/first-dataset.md` (PokéAPI example). "A REST table may call its source again for each query", so `CACHE TABLE` it.

## 7. Federated query

Command reference §3 rule 5: "Registered tables are queried with standard Spark SQL, for example `SELECT … FROM crm_pg.customers`, and may be joined across sources."

INFERRED example for StockWhy (not run):
```sql
SELECT s.facility_id, s.month, s.closing, o.order_date, o.cutoff_date, p.amount_owed_kes
FROM stockwhy_pg.stock s
JOIN stockwhy_pg.orders o ON o.facility_id = s.facility_id AND o.commodity = s.commodity AND o.month = s.month
JOIN stockwhy_files.payments p ON p.month = s.month          -- a second source makes it federated
WHERE s.facility_id = 'FAC-009' AND s.commodity = 'ORS sachet'
```

## 8. Rules to bake into the client

- "Send one Lightning SQL statement per call." (client-setup.md)
- "Commands that operate on a table require the form `<source>.<table>`." (`Table not found` → qualify it)
- `SHOW DATASOURCES` lists JDBC sources only; "Use `SHOW LIGHTNING DATABASES` for REST and file sources."
- Least privilege: "agents and applications that only read should use their own non-administrator user". CREATE DATASOURCE, CREATE LIGHTNING DATABASE and FILESTORE TABLE are "Administrators only".
- Self-join on a `UNION ALL`/`explode()` view fails with `MISSING_ATTRIBUTES.RESOLVED_ATTRIBUTE_APPEAR_IN_OPERATION`; use window functions instead (SQL companion §4).
- `CACHE TABLE` is a session cache; "Do not assume view replacement preserves its cache." (§5)
- Live-tested version referenced: "Zetaris 2.4.3.1" (12 Oct 2026).

## 9. Minimal Python client shape (from Zetaris's own RestChannel; for the build engineer)

```python
import json, os, uuid, urllib.request
def zetaris_sql(sql: str, limit: int = 100):
    base = os.environ["ZETARIS_REST_URL"].rstrip("/")
    req = urllib.request.Request(
        base + "/sql-editor/sqls/run",
        data=json.dumps({"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": limit}).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {os.environ['ZETARIS_API_KEY']}",
                 "X-Org-ID": os.environ["ZETARIS_ORG_ID"],
                 "X-Request-ID": str(uuid.uuid4()),
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        out = json.loads(r.read().decode() or "null")
    return out.get("data") if isinstance(out, dict) else None   # rows: list of lists of strings
```

## 10. Onboarding calls and support

- "Workshop: Data Day with Zetaris", Oct 12, "3 PM PT (22:00 UTC)" (academy page, see SCHEDULE.md). Already passed. Recording: **NOT FOUND**.
- Support: Zetaris Discord https://discord.gg/GTmaNZyJnH (zetaris.com), Knowledge base https://kbase.zetaris.com/knowledge/sql-guide.

## 11. HackOS Participant Setup Guide (logged-in pass; overrides §1 where they differ)

Source: HackOS Resources > Participant Setup Guide (PDF, "Last updated 21 October 2026"), section 01 Data.

- Instance: "For this hackathon, everyone runs Zetaris locally in Docker." No shared event instance is mentioned.
  "Register at cloud.enterprise.zetaris.com/register, then open the Run locally page at
  cloud.enterprise.zetaris.com/dashboard/download to download zetaris-platform.zip and copy the registry sign-in
  command." Registry: `docker login zetarishackathon.azurecr.io`. Credentials: `<present in Zetaris Cloud: Run locally page>`.
- Hardware: "Zetaris needs 8 GB of memory and 4 CPUs given to Docker, plus at least 15 GB of free disk space."
  Under 16 GB RAM: managed AWS cluster on a new AWS Free plan account ("up to US$200 in credits").
- Steps: `./preflight.sh` → set `ZETARIS_ADMIN_EMAIL`, `ZETARIS_ADMIN_PASSWORD`, `ZETARIS_ADMIN_ORG` in the platform
  `.env` before first start → `docker compose pull && docker compose up -d` → `./verify.sh` ("9 / 9 passed") →
  SQL Editor at `http://localhost:3000`, `SELECT 1 AS one;`. "The first download and startup take 30 to 45 minutes."
  Apple Silicon: "turn on Use Rosetta in Docker Desktop's settings".
- Routes on a local install (exact): web UI `http://localhost:3000`; REST API `http://localhost:8888/api/v1.0`;
  JDBC `jdbc:zetaris:lightning@localhost:10000`. API docs at `http://localhost:8888/redoc/index.html`.
  "Don't use port 8889: it's internal to Zetaris."
- App `.env` (exact keys): `ZETARIS_REST_URL=http://localhost:8888/api/v1.0`, `ZETARIS_ORG_ID=1`,
  `ZETARIS_API_KEY`, `ZETARIS_USERNAME`, `ZETARIS_PASSWORD`. "1 is the organisation ID on a local install. The
  username and password are only needed to download the API's specification."
- Every REST request: `POST /sql-editor/sqls/run` with `Authorization: Bearer <API key>`, `X-Org-ID`, `X-Request-ID`
  ("a fresh UUID"). The smoke test body is `{"queryId": <uuid>, "sql": "SELECT 1", "source": "SqlEditor", "limit": 1}`
  and it reads `response.json().get("data")`, which matches §4.
- API key: "create an API key for your user and copy it straight away (it may be shown only once). Create the key
  yourself; don't ask an AI agent to create or fetch it."
- Errors (Troubleshooting table): 401 = "The Zetaris API key is missing, wrong or expired"; 400 = "Wrong X-Org-ID, or
  X-Request-ID isn't a UUID"; "A file on your laptop won't query: Zetaris can't read files on your laptop. Put the
  file in storage Zetaris can reach, such as an S3 bucket, then register it."
- Suggested pattern for our track ("Putting it together"): "Your agent queries Zetaris first for the facts, and uses
  web data only to add context. Judges and users can trust answers that trace back to governed data, which is what
  The Agent That Can Explain Why track asks for."
- Data rule for judges (Disqualification Checklist): "Data setup is automated, including any sources registered in
  Zetaris". HackOS FAQ: "include a sample mode so your solution still runs without Zetaris, Nightshift or live credentials".
- HackOS Resources > Zetaris getting-started prompt pins the repo at commit
  `44668b267ad7ee0fae25ce7588e9620121d47cae` and runs `python3 scripts/preflight.py --jdbc`.
- The Zetaris sponsor overview still says "[TBC: instance access and the Zetaris documentation will be added to
  this folder before the build window opens on 22 October.]" (unchanged on 23 Oct).

