# Open questions for organisers

Where to ask: HackOS #help desk (general), Help Zetaris / Help Meterless / Help Cursor / Help NVIDIA Tools (sponsor),
general-admin (programme and logistics), hackathons@genai.works (rules, per the onboarding deck). Ordered by impact.

Answered by the logged-in pass (2026-10-23), so removed: Zetaris instance (local Docker for everyone), Meterless
integration bar (one Engine in a working feature + Nightshift as primary provider), submission form fields, in-kind
prize breakdown, Build/Power workshop dates and recordings.

## Blocking

1. **Cursor: required or optional?** Event page Rule 5 says "teams must use Cursor for development" and the Help
   Cursor channel says it is "the required development environment". HackOS FAQ and the 22 Oct announcement say
   "Cursor is now optional". Which one is binding? If optional, can we leave Cursor out of the sponsor explanation?
2. **Pre-existing work:** our repo has commits from 14 Oct and 20 Oct (before 22 Oct 00:00 UTC), and our synthetic
   datapack was prepared around 22 Oct. Is it enough to declare both in the form's "pre-existing components" field?
   Should we date the datapack's creation?
3. **Bright Data:** the 22 Oct announcement mentions a "Help Bright Data" channel, but no such channel or document
   exists. Is there a Bright Data bounty, prize or credits?
4. **metadata.json:** sponsor overviews say to describe sponsor use in "`metadata.json`", but the form has no such
   field and there's no template. Is it required? Is there a schema?

## Important

5. **Sponsor credits:** the FAQ says credits are "On the HackOS task board, once you have created your team". Our
   board's "Get sponsor credits" task is empty. How do we claim NVIDIA (and Meterless) credits?
6. **Nightshift on judges' machines:** judges run with `SAMPLE_MODE=true` if Nightshift isn't available. Will judges
   run Nightshift at all, or is the demo video the only evidence of the Nightshift path?
7. **Meterless Engine in Python:** is a Python implementation of an engine spec, tested against the engine's JSON
   conformance vectors (not the TypeScript runner), accepted as "conformance suite, evaluation or a reproducible
   feature test"?
8. **Zetaris data from files:** "Zetaris can't read a file sitting on your laptop". For a local Docker install, is
   a Postgres container on the same Docker network the recommended path for CSVs, or is there a local file store?
9. **Rubric:** the Meterless repo's hackathon guide shows a different rubric (Meterless engine usage 25%) and dates
   (Oct 15–20). Confirm the HackOS/event page rubric (Impact 30 / Technical 20 / Innovation 15 / Demo 15 / Product &
   UX 10 / Sponsor Tech 10) is the only one.

## Nice to know

10. Exact time of the POWER workshop (19 Oct) and any fixed office-hour slots.
11. Does the Zetaris REST `/sql-editor/sqls/run` response include column names? (Answer from
    `http://localhost:8888/redoc/index.html` once our instance runs.)
12. Is there a Zetaris MCP server for agents? (zetaris.com mentions "MCP / REST"; HackOS docs only describe REST and JDBC.)
13. Registration closed at 23:45 or 23:59 UTC on 22 Oct? (Sources differ; doesn't affect us.)
