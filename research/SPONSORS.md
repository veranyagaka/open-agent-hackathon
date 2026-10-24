# Sponsors

Logged-in pass done 2026-10-23. HackOS Resources holds 68 items: Zetaris folder 24, Meterless 6, NVIDIA 1, Cursor 1
(mostly links into the Zetaris getting-started repo and the Meterless engine guides). HackOS paths below are document
titles in https://hackathon.genai.works/resources.

Sponsor lists disagree:
- HackOS FAQ / Hackathon Overview / Official Rules draft: "Space XAI (with Cursor), NVIDIA, Zetaris and Meterless".
- Event page logos: NVIDIA, Zetaris, SpaceX AI, Meterless.
- NCSA news post (secondary): "NVIDIA, Space XAI (with Cursor), Bright Data, Zetaris and Meterless".

Requirement summary (HackOS Hackathon Overview, exact):
| Sponsor | Requirement |
|---|---|
| Zetaris | "Required: every submission must use Zetaris as its data layer" |
| Meterless | "Required: every submission must implement at least one Meterless Engine (H-MEM, Markovian, World Model or Scout Intent) in a working feature, and use Meterless Nightshift as its primary AI provider" |
| Cursor (with Space XAI) | "Optional: recommended AI coding tool. Teams can build with any coding tool" |
| NVIDIA | "Integrate wherever it contributes. NVIDIA models are connected through Nightshift" |

"Mentioning a sponsor technology, copying a prompt or adding an unused dependency does not meet these requirements.
The integration must work in the submitted project." Sponsor Tech is 10 of 100 rubric points.

---

## Zetaris (required: data layer)

**What it is:** a federated SQL / data-fabric platform ("Lightning" SQL on Spark). It registers databases, files and
REST APIs as sources and queries them together. Full client detail: ZETARIS_API.md (§11 has the HackOS setup).

**Setup (HackOS Participant Setup Guide):** "For this hackathon, everyone runs Zetaris locally in Docker." Register at
Zetaris Cloud, download `zetaris-platform.zip`, `docker login zetarishackathon.azurecr.io`, then `docker compose up -d`.
Needs 8 GB RAM / 4 CPUs for Docker and 15 GB disk; 30–45 min first start. AWS managed cluster if under 16 GB RAM.

**How to call:** REST `POST http://localhost:8888/api/v1.0/sql-editor/sqls/run` with Bearer API key + `X-Org-ID: 1` +
`X-Request-ID` (UUID); JDBC `jdbc:zetaris:lightning@localhost:10000`; SQL Editor at `http://localhost:3000`.

**Limits:** one statement per call; REST values come back as strings; "Zetaris can't read a file sitting on your
laptop" (use Postgres or S3); external REST sources are re-called on every query unless cached.

**What judges want:** demo video must show "how Zetaris and Meterless are integrated" (Submission Requirements).
Setup Guide pattern for our track: "Your agent queries Zetaris first for the facts, and uses web data only to add
context." Disqualification Checklist: "Data setup is automated, including any sources registered in Zetaris".
INFERRED: show a real cross-source join (for example Postgres stock/orders + S3 notices), not Zetaris as a
single-table proxy.

**Still open:** the Zetaris sponsor overview "Getting access" section is still "[TBC ...]".

---

## Meterless (required: one Engine in a feature + Nightshift as primary AI provider)

Two separate requirements (Setup Guide):
1. **Build rule:** "you must implement at least one Meterless Engine in a working feature of your product."
   Engines: H-MEM (memory), Markovian (bounded long tasks), World Model (shared state), Scout Intent (routing and risk).
   Evidence wanted: "The engine's conformance suite, evaluation or a reproducible feature test passes, and you can
   show the evidence." "For your submission: name the engine(s), explain what each one does in your project, and show
   the working feature and test result."
2. **Power rule:** "your app must support Meterless Nightshift as a primary AI provider." The Add-Meterless-as-provider
   prompt "On its own, ... doesn't meet the Build requirement".

**Nightshift Runtime (Setup Guide 4.5–4.6, exact):** `.env` keys `METERLESS_BASE_URL=http://127.0.0.1:8088/v1`,
`METERLESS_RUNTIME_TOKEN=<present in Nightshift: Console>`, `METERLESS_MODEL=meterless/auto`. Contract:
"Authorization: Bearer <token>, the meterless-app header, meterless-scope: user for chat, GET /v1/models for discovery
and OpenAI-compatible POST /v1/chat/completions." "A working /healthz response isn't proof that a real model is
connected." Install: meterless.ai install cards (Windows, Mac M1+, Mac M5+, DGX); email verification gate.
"The free browser experience ... don't assume a browser demo exposes the local Runtime your app needs."

**Engines are specs, not packages** (https://github.com/meterless/meterless, commit `1742dec`): "An engine here is an
implementation spec for coding agents, not an npm package." The reference code is TypeScript; the repo has no Python.
engines/hmem/README.md: "Implement it in TypeScript, Python, Rust, or whatever stack you ship. The contracts do not
change." HackOS Meterless Agent Engines Index: "all model usage goes through an injected generator" and the engines
should include "a sample mode that runs with no credentials". All three emit "JSONL audit/telemetry/provenance
designed to be shipped to a run's `logs/` directory as evidence for judges".

**Track fit (Agent Engines Index, exact; its track names differ from this event's tracks):** "Autonomous Intelligence | Markovian for the long investigation, World
Model for the evidence trail". INFERRED for StockWhy: World Model for facilities/medicines/orders with provenance;
H-MEM for remembered facility history; Scout Intent as the "pharmacist approves" risk guard.

**Limits:** Nightshift hotspot latency on DGX Spark, "median latency was 36.8 s and p95 was 5 minutes 7 seconds"
(docs/products/nightshift/hotspot.md). The provider doc says "Use a 180 s timeout".

---

## NVIDIA (where it contributes; through Nightshift)

See NVIDIA_MODELS.md. The NVIDIA key goes in Nightshift's Providers tab, never in our app. Award: DGX Spark ($4,699)
for using "at least one Nemotron model through Meterless Nightshift in a working feature, and show which model
handled the request." Credits: "On the HackOS task board" (FAQ), but our board task has no details, so **NOT FOUND**.

---

## Cursor (optional per HackOS; "must use" per the event page)

- HackOS FAQ: "No. Cursor is optional and recommended." 22 Oct announcement: "Cursor is now optional" and "No free
  Cursor credits are included with this event".
- Event page Rule 5 still says "teams must use Cursor for development", and the HackOS "Help Cursor" channel says
  "Cursor is the required development environment for every submission".
- Award: "Best Cursor-built product | Cursor API credits | $2,301" (Hackathon Overview).
- The submission form still asks how Cursor was used (Submission Form Preview).
- INFERRED: since the binding rules are on the event page, use Cursor for at least part of the build and keep evidence
  (for example `.cursor/rules` and screenshots) until organisers confirm (OPEN_QUESTIONS.md).

---

## Bright Data (bounty unconfirmed)

- No HackOS document mentions Bright Data (grep over every downloaded doc: 0 matches). The event page, academy page
  and rules don't mention it either.
- The only HackOS trace is the 22 Oct announcement listing "Help Bright Data" among sponsor channels. There is no
  such channel in the Messages list (read 23 Oct).
- If we use it anyway (public-source notes): **Web Unlocker** `POST https://api.brightdata.com/request`,
  `Authorization: Bearer <present in Bright Data account>`, body `{"zone":"...","url":"...","format":"raw"}`
  (https://docs.brightdata.com/scraping-automation/web-unlocker/introduction). **SERP API**: same endpoint with a SERP
  zone and optional `data_format` `parsed_light` / `markdown`
  (https://docs.brightdata.com/scraping-automation/serp-api/introduction). Free credits: **NOT FOUND**.
- INFERRED: any web data should feed *into* Zetaris (for example as a registered table), because the Setup Guide
  says web data should "only ... add context".

---

## Space XAI (with Cursor)

Listed as a sponsor "with Cursor". No technology requirement of its own. The judge list includes Michael Armentano
(SpaceXAI) (event page).
