# Open questions for organisers (Discord / HackOS / hackathons@genai.works)

Ordered by impact on our build.

## Blocking

1. **Bright Data bounty:** does a Bright Data bounty exist for this event? It isn't on the event page, in Rules 1–10 or on the academy page. If it exists, what are the criteria, the prize and the credits?
2. **Zetaris instance:** do teams get a shared event instance (the getting-started repo's plan mentions "Shared event instance: confirmed. Require an assigned team prefix"), or must each team run its own local/AWS install? If shared, what are the URL, org ID and our team prefix?
3. **Meterless integration bar:** what counts as "integrate Meterless"? (a) running a Node reference engine as-is, (b) a Python implementation of an engine spec (H-MEM / World Model / Scout Intent), or (c) routing model calls through the Nightshift runtime (`http://127.0.0.1:8088/v1`)? Is a Python port without a passing TS conformance run acceptable?
4. **Pre-existing code:** our repo has commits dated 14 Oct and 20 Oct 2026 (before the 22 Oct window). Is declaring them in the submission form enough, and where in the form?
5. **Submission form:** what fields does it have, with what limits (video host, deck format, max length), and is a metadata.json required? (Not visible without login.)

## Important

6. **NVIDIA:** are there hackathon credits or raised rate limits for build.nvidia.com, and how do we claim them? What are the judging criteria for "Best use of NVIDIA Nemotron"?
7. **Rubric:** the Meterless repo's hackathon guide shows a different rubric (Meterless engine usage 25%) and dates (Oct 15–20). Confirm the event page rubric (Impact 30 / Technical 20 / Innovation 15 / Demo 15 / Product & UX 10 / Sponsor tech 10) is the only one that applies.
8. **Cursor evidence:** what proof of "teams must use Cursor for development" do judges expect?
9. **In-kind prizes:** Rule 8 says "$7,000 in in-kind rewards" but itemises only the $4,699 DGX Spark. What is the rest?
10. **Zetaris MCP:** zetaris.com mentions "MCP / REST" and a Cursor connection guide. Is there a Zetaris MCP server URL/config for agents?

## Nice to know

11. Is there a recording of "Data Day with Zetaris" (Oct 12, 22:00 UTC)?
12. What are the dates and times of the "Build Day" and "Power Day" workshops and the mentor office hours?
13. Can we upload CSV files into Zetaris "platform storage" (listed in command reference §5), or must data sit in Postgres/S3?
14. Does the Zetaris direct REST `/sql-editor/sqls/run` response include column names? (The repo only shows `data` as rows of strings.) Answer by fetching `/redoc/docs.yaml` once we have an instance.
