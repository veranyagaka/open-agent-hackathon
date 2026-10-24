# StockWhy

The full project context (rules, requirements, current state, guardrails) is shared with Cursor and lives here:

@.cursor/rules/stockwhy-context.mdc

Sourced research with exact quotes: `research/`. Data: `data/README.md`. Evaluation: `eval/README.md`.

## Working in a cloud session

- The cloud machine **cannot reach Zetaris or Meterless Nightshift**. Both run on a teammate's laptop
  (`localhost:8888`, `127.0.0.1:8088`). In the cloud, develop and test with `SAMPLE_MODE=true` only, reading
  `data/sample/` and `data/cases/`.
- Write the Zetaris and Nightshift clients against the documented contracts (see the context file and
  `research/ZETARIS_API.md`). Keep the I/O behind one interface so sample mode and live mode share the agent logic.
  Live integration is tested locally.
- Install with `pip install -r requirements.txt`. Don't expect a `.env` here, and never create one with real values.
- Commit with plain messages. Don't add AI co-author trailers.
