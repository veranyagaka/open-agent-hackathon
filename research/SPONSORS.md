# Sponsors

> HackOS resource folders (https://hackathon.genai.works/resources) redirect to sign-in and were **not read**
> (Claude in Chrome was not connected). Everything below is from public primary sources. A logged-in pass must still
> list each HackOS folder's documents.

Sponsors on the event page: NVIDIA, Zetaris, SpaceX AI, Meterless (logos linking to nvidia.com, zetaris.com, x.ai,
meterless.ai). The academy page lists "Sponsor technologies: Zetaris, Cursor, Meterless and NVIDIA Nemotron". Only a
university news post (NCSA) lists "NVIDIA, Space XAI (with Cursor), Bright Data, Zetaris and Meterless".

---

## Zetaris (required)

**What it is:** a federated SQL / data-fabric platform ("Lightning" SQL on Spark). It registers databases, files and
REST APIs as sources and queries them together. Full client detail: ZETARIS_API.md.

**Setup:** your own instance, either local Docker (~20–30 min, 8 GB RAM for Docker, amd64 images emulated on Apple
Silicon) or a managed AWS Mini cluster (~30 min, from new-account Free Tier credits). Source: https://github.com/zetaris/getting-started START-HERE.md.

**How to call:** direct REST `POST {base}/api/v1.0/sql-editor/sqls/run` with a Bearer API key + `X-Org-ID` +
`X-Request-ID`; or JDBC `jdbc:zetaris:lightning@host:10000`; or the SQL Editor UI.

**Limits:** one statement per call; admin-only CREATE; REST values come back as strings; local laptop files can't be
read (use Postgres or S3); external REST sources are re-called on every query unless cached.

**What judges want:** Rule 6: "how Zetaris and Meterless are integrated" in the video; "how Zetaris and Meterless were
used, what was unique about your use" in the deck. A Zetaris CTO (Michael Hay) is on the judging panel. Zetaris's START-HERE
says to use the demo template "to save your SQL, results and steps someone else can reproduce" (template at `docs/guides/demo-template.md`).
INFERRED: show a real cross-source join in Zetaris (for example Postgres stock/orders + S3/REST notices), not Zetaris
used as a single-table proxy.

**Open questions:** shared event instance or our own? Is there an MCP server? Recording of Data Day? (OPEN_QUESTIONS.md)

---

## Meterless (required)

**What it is** (https://github.com/meterless/meterless, commit `1742dec`, 2026-10-19): two parts.
1. **Nightshift**, the paid local runtime ("Turn your computer into an AI hotspot."). Editions: Web (free, browser,
   no hotspot), Windows 1.2.1 ("Out now", dedicated GPU), Mac M5+ (preorder, $199, "delivery Q4 2026"), Mac M1+
   ("Free download", "A local endpoint"), DGX ("On request").
2. **Four open "engines"**, which are specs, not packages: "An engine here is an implementation spec for coding agents,
   not an npm package. Each folder has a full `AGENTS.md` contract, runnable examples, workshops, and a conformance
   suite".
   - **H-MEM**: hierarchical memory with provenance and an append-only trust ledger (reference + conformance)
   - **World Model**: event-sourced entity/state graph (reference + conformance)
   - **Markovian**: bounded-context long runs (reference + conformance)
   - **Scout Intent**: intent, risk guard, tool routing, "signed execution contracts" (spec + eval harness only)

**Node as-is vs a Python port vs Nightshift?** This is the question we need answered. What the sources say:
- The references are TypeScript (`npx tsx`, `npm test`). The repo contains **no Python files**.
- A Python port is explicitly allowed: engines/hmem/README.md says "H-MEM is a reference architecture. ... Implement it
  in TypeScript, Python, Rust, or whatever stack you ship. The contracts do not change."
- The conformance runner loads a TS module: `HMEM_IMPL=/abs/path/to/your/index.ts npx tsx conformance/runner.ts`
  ("Set HMEM_IMPL to an absolute path exporting an HMEM class."). INFERRED: a Python port can't be checked by the
  runner without a TS shim, but the `conformance/vectors/vectors.json` test vectors are plain JSON and reusable.
- Starter template: `npx degit meterless/meterless/templates/agentathon-starter my-agent` (a TS CLI with real H-MEM).
- Nightshift as a model provider (`docs/agent-ready/add-meterless-provider.md`, "Meterless Runtime 0.90.0"):
  OpenAI-compatible, "default base URL http://127.0.0.1:8088/v1", "Send Authorization: Bearer <token> on every call.
  The runtime writes the token to <stateDir>/proxy-token. ... The placeholder rt-local is rejected.", headers
  `meterless-app: <stable lowercase id>` and `meterless-scope: user` on chat; model IDs are routing modes
  `meterless/auto|fast|deep|cheap|local|fusion`; "Use a 180 s timeout".
- Which of these the judges expect: **NOT FOUND**. The event rules only say "must integrate ... Meterless".

**Mapping to StockWhy (INFERRED):** H-MEM trust ledger and provenance fit "explain why" well ("Why did the agent say
March 14?" is answered by a "five-line ledger trace", engines/README.md). World Model fits facilities/medicines/orders
as entities. Scout Intent fits the "pharmacist approves the action" guard.

**What judges want (Meterless's own view, from an older/different rubric):** agentathon-starter README: "The rubric
weights 'Meterless engine usage' at 25%. Every command routes through a named H-MEM service; nothing is faked" and
"Where the engine is used (judges look here)". So: map each feature to a named engine service in the README.

**Limits:** Nightshift hotspot latency on a DGX Spark, "median latency was 36.8 s and p95 was 5 minutes 7 seconds"; "When
someone is waiting, rent latency from the cloud." (docs/products/nightshift/hotspot.md). Mac M5 edition not shipping yet.

---

## NVIDIA (where it contributes; prize: DGX Spark for "Best use of NVIDIA Nemotron")

See NVIDIA_MODELS.md. Base URL `https://integrate.api.nvidia.com/v1` (OpenAI-compatible). Hackathon credit process:
**NOT FOUND** publicly. Judging criteria for the Nemotron prize beyond its title: **NOT FOUND**. Rule 6 requires
explaining "where NVIDIA technology contributes".

---

## Cursor (required for development)

Rule 5: "teams must use Cursor for development." Rule 6 asks for "how Cursor was used during development". Credits,
setup docs or any proof format (screenshots, `.cursor/rules`, commit trailers): **NOT FOUND** publicly. Both Zetaris
(`docs/connections/cursor-connection.md`) and Meterless (`docs/agent-ready/using-with-cursor.md`) have Cursor guides.
INFERRED: commit `.cursor/rules` or AGENTS.md and keep screenshots of Cursor sessions as evidence.

---

## Bright Data (bounty?)

- Not on the event page, the academy page or the official rules. **No Bright Data bounty found in any primary source.**
  The only mention is the NCSA news post sponsor list. Treat the bounty as unconfirmed (OPEN_QUESTIONS.md).
- Product fit for public news/tender pages (KEMSA notices, county budget pages):
  - **Web Unlocker**: "unlocks any public web page in a single API call with a 98% success rate and returns clean HTML
    or JSON." `POST https://api.brightdata.com/request`, `Authorization: Bearer YOUR_API_KEY`, body
    `{"zone":"YOUR_ZONE_NAME","url":"https://example.com","format":"raw"}` (https://docs.brightdata.com/scraping-automation/web-unlocker/introduction). This fits fetching known notice pages.
  - **SERP API**: the same endpoint with a SERP zone; `url` is a search URL; optional `data_format`
    (`parsed_light` = top 10 organic results, `markdown`) (https://docs.brightdata.com/scraping-automation/serp-api/introduction). This fits *finding* new notices ("KEMSA stock-out oxytocin 2026").
  - INFERRED: SERP API to discover, Web Unlocker to fetch.
- Free credits: **NOT FOUND**. Both pages say only "Pay only for successful" requests/delivery.

---

## SpaceX AI

Listed as a sponsor; Michael Armentano (SpaceXAI) is a judge. No technology requirement in the rules. Nothing further found.
