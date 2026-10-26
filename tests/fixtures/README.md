# Test fixtures copied from Meterless (Apache-2.0)

Source: https://github.com/meterless/meterless (main, read 2026-10-23). Unmodified copies:

| File | Upstream path |
|---|---|
| `hmem_vectors.json` | `engines/hmem/conformance/vectors/vectors.json` |
| `scout_injection_adversarial.jsonl` | `engines/scout-intent/evals/regression-set/v1/injection/adversarial.jsonl` |

They are pre-existing third-party components (Apache-2.0), see `engines/README.md`.

`stockwhy_injection_extra.jsonl` is ours (not from Meterless): StockWhy-specific injection, secret-exfiltration and
hard-negative requests, scored end to end through `engines.scout_intent.gate` in `tests/test_engine_scout_intent.py`.
