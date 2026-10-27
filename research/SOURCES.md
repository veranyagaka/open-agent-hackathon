# Sources read (all accessed 2026-10-23)

## HackOS (logged in with Claude in Chrome, read only)

| Source | Used for |
|---|---|
| https://hackathon.genai.works/dashboard | Countdown, submission status (NOT STARTED), announcements |
| Team page `/team/019fd164-82b9-7382-a536-d9093c576ed2/01a1507b-b900-7d63-be3c-1a53af395abd` and task board `/board?hackathon_id=019fd164-...` | Team NexusForge, 3 members, no track set, empty "Get sponsor credits" task |
| https://hackathon.genai.works/messages, Announcement channel (1–23 Oct posts) and channel list | Cursor-optional update, workshop times, opening ceremony, channel names |
| https://hackathon.genai.works/resources: 68 items. Documents downloaded as Markdown/PDF with user approval: Official Rules (draft), Submission Requirements, Submission Form Preview, Disqualification Checklist, Technical Execution Requirements, Team Formation Rules, Event Calendar, Welcome Guide, Participant Journey Map, Hackathon Overview, How APPROACH Solutioning For Your Use Case, Vibe Coding Starter Guide, Winner Next Steps, AI Usage Policy, Code of Conduct, FAQ, Channel Directory, Escalation Path, Help Desk Instructions, Troubleshooting Guide, Mentor Office Hours Guide, Weak/Strong Submission Examples, Demo Video Guide, NVIDIA / Zetaris / Cursor / Meterless sponsor overviews, Zetaris getting-started prompt, Meterless Agent Engines Index, Participant Setup Guide (PDF, 21 Oct), Onboarding Call deck (PDF), Day 4 Check-in deck (PDF) | RULES.md, SPONSORS.md, ZETARIS_API.md §11, NVIDIA_MODELS.md (HackOS section), SCHEDULE.md, OPEN_QUESTIONS.md |

Not opened: the submission "Open" button (creating a submission locks the team), team settings, and the challenge
statement pages (`/hackathons/<id>` redirected to the dashboard). Workshop videos were not watched.

## Public

| Source | Used for |
|---|---|
| https://hackathon.genai.works/event/open-agent-hackathon-2026 (public HTML + embedded page data for collapsed rules/FAQ) | Rules 1–10, rubric, tracks, prizes, dates, FAQ, judges |
| https://academy.genai.works/courses/open-agent-hackathon-2026/details | Live-session schedule, sponsor technology list |
| https://ai.ncsa.illinois.edu/illinois-students-invited-to-form-teams-and-build-ai-solutions-on-a-global-stage/ | Only source listing Bright Data as a sponsor (secondary) |
| https://github.com/zetaris/getting-started (commit 6a2fbaa, 2026-10-22): START-HERE.md, README.md, .env.example, scripts/HOWTO.md, scripts/zetaris_api.py, scripts/zetaris_sql.py, scripts/query_zetaris.py, scripts/check_zetaris.py, scripts/run_sql.py, scripts/preflight.py, examples/pudl-chart/render.py, docs/connections/{README,client-setup,cursor-connection,lightning-recipe-reference}.md, docs/install/{choose-install,updated_zetaris_installation_guide,managed-aws-cluster-guide}.md, docs/guides/{troubleshooting,permissions,zetaris-lightning-sql-companion}.md, docs/guides/zetaris-lightning-sql-commands.md (§1–5), open_data/parquet_csv/HOWTO.md, docs/plans/hackathon-user-journey.md | ZETARIS_API.md |
| https://www.zetaris.com/ | Links to kbase, register, Discord; "MCP / REST" mention |
| https://kbase.zetaris.com/knowledge/coding-agent-connection-guide-cursor | Body did not render (JS only); nothing usable |
| https://github.com/meterless/meterless (commit 1742dec, 2026-10-19): README.md, engines/README.md, engines/hmem/README.md + conformance/, docs/community/hackathon-guide.md, docs/agent-ready/add-meterless-provider.md, docs/products/nightshift/hotspot.md, templates/README.md, templates/agentathon-starter/README.md | SPONSORS.md Meterless |
| https://integrate.api.nvidia.com/v1/models | Exact model IDs |
| https://docs.api.nvidia.com/nim/reference/llm-apis and per-model pages nvidia-nemotron-3-super-120b-a12b, nvidia-nemotron-3-ultra-550b-a55b, nvidia-nemotron-3_5-super-vl-120b-a12b, nvidia-nemotron-3-nano-30b-a3b, nvidia-llama-3_3-nemotron-super-49b-v1_5 (plus nvidia-nemotron-3_5-lightning-30b-a3b and nvidia-nemotron-nano-3-30b-a3b, which returned a generic page) | NVIDIA_MODELS.md |
| https://forums.developer.nvidia.com/t/request-for-nvidia-build-api-rate-limit-increase-40-rpm-200-rpm/377433 (via search) | Rate limit (unofficial) |
| https://docs.brightdata.com/scraping-automation/web-unlocker/introduction | Web Unlocker API |
| https://docs.brightdata.com/scraping-automation/serp-api/introduction | SERP API |
| data/sample/zetaris_register.sql, data/DATA_DICTIONARY.md, data/PUBLIC_DATA_SOURCES.md | Checked our Zetaris SQL against the command reference |
