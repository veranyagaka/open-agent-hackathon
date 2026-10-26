# Meterless engines in StockWhy

Two [Meterless](https://github.com/meterless/meterless) engines, ported to pure-stdlib Python (Apache-2.0
upstream). Both are deterministic, make no network calls and are covered by tests that run on the upstream
fixtures.

| Engine | File | What it does in StockWhy | Tests |
|---|---|---|---|
| Scout Intent | `scout_intent.py`, `intents.json` | Gates every request before any agent runs: blocks prompt injection and secret exfiltration, refuses out-of-scope asks (placing orders, dosing advice), asks for clarification when the facility, medicine or month is missing or not in the data, and otherwise issues a signed, 5-minute capability contract. | `tests/test_engine_scout_intent.py` |
| H-MEM | `hmem.py` | Case memory: each finding is stored with the evidence row IDs and run ID behind it, recalled before the next investigation of the same facility and medicine, and updated by the pharmacist's approve/reject. Every change goes to an append-only ledger. | `tests/test_engine_hmem.py` |

## Interface

```python
from engines.scout_intent import gate, Contract, ContractViolation
from engines.hmem import CaseMemory

g = gate({"question": "...", "facility_id": "FAC-016", "commodity": "oxytocin 10IU inj",
          "month": "2026-03", "role": "pharmacist"}, dataset)   # dataset: load_dataset(...) or None
g["decision"]   # "allow" | "clarify" | "refuse" | "block"
g["intent"], g["band"], g["reason"], g["trace"]
g["params"]     # values bound to the data (e.g. "ors" -> "ORS sachet"); g["suggestions"] on clarify
c = g["contract"]            # Contract on allow, else None
c.check("data.read")         # raises ContractViolation if expired, tampered, or not granted
d = c.child("action.draft", {"data.read", "action.draft"})   # signed, parent_id = c.id
c.to_dict()                  # for the run log

mem = CaseMemory("logs/memory/hmem.json")
mem.recall("FAC-016", "oxytocin 10IU inj", limit=5)   # newest first: id, month, cause, summary, citations, status, provenance
mid = mem.store({"facility_id": ..., "commodity": ..., "month": ..., "cause": "h1_late_order", "summary": ...},
                citations=["orders#3161", "stock#1506"], run_id=run_id)   # status "pending_approval"
mem.feedback(mid, "approve" | "reject", note="")
```

An allowed request gets intent `stockout.explain` with capabilities `data.read`, `llm.call`, `memory.read`,
`memory.write`. Drafting actions needs a child contract with `action.draft`, which carries a `pharmacist-confirm`
approval. **No capability exists for `order.send`**: an intent that needs it is refused, and `Contract.issue` /
`child` raise `ContractViolation` if asked for it. The signing key comes from `SCOUT_SIGNING_KEY`, or is random
per process.

`store` rejects a finding without a `run_id` (H-MEM's mandatory source) or without cited evidence rows.
Records are kept in `hmem.json`; the audit ledger is `hmem.ledger.jsonl` next to it.

## Mapping to the Meterless spec

| Spec (upstream) | Here |
|---|---|
| `engines/scout-intent/AGENTS.md`: Sense (Stage-1 lexical scoring, bands High >= 0.80, Medium >= 0.55, Low >= 0.40, else Reject) | `classify`, `band_for`; triggers in `intents.json` (English and Swahili). Stage 2 (optional) is not implemented. |
| Interpret (parameter binding, clarification on low band or missing params) | `bind`, `gate` -> `clarify`, with close-match suggestions from the data |
| Guard (injection, role/scope, PII) | `scan_injection` on every request field, role check from the registry, PII flags in the trace |
| Route (capability graph; missing capability = refuse) | `CAPABILITY_GRAPH`; `order.submit` and `clinical.advice` are refused |
| ExecutionContract (signed, expiring, `parentId` re-plan) | `Contract` (HMAC-SHA256 over the canonical body, 5-minute TTL, `child`) |
| `engines/scout-intent/evals/regression-set/v1/injection/adversarial.jsonl` with recall >= 0.82, precision >= 0.90 floors | `tests/fixtures/scout_injection_adversarial.jsonl`, scored end to end through `gate` |
| `engines/hmem/AGENTS.md`: records need a source, hybrid retrieval, feedback deltas (+0.05 / -0.03 / -0.20), conflict gate, sleep cycle, human-approved dreaming, append-only trust ledger | `HMEM` and its parts in `hmem.py` |
| `engines/hmem/conformance/vectors/vectors.json` and `conformance/runner.ts` | `tests/fixtures/hmem_vectors.json`, run by the Python port of the runner in `tests/test_engine_hmem.py` |

The fixtures are unmodified upstream copies (see `tests/fixtures/README.md`).
