"""
engines/hmem.py

H-MEM (Meterless engine), a Python port of the spec at
https://github.com/meterless/meterless/blob/main/engines/hmem/AGENTS.md (Apache-2.0).

The core (HMEM: records with mandatory source and provenance, hybrid retrieval, feedback deltas, conflict gate,
sleep cycle, human-approved dreaming, append-only trust ledger) is checked against the engine's own conformance
vectors (tests/fixtures/hmem_vectors.json, run by tests/test_engine_hmem.py).

In StockWhy it is case memory (CaseMemory, at the bottom of this file): each finding is stored with the row IDs
behind it and the run that produced it, recalled before the next investigation of the same facility and medicine,
and the pharmacist's approve/reject is fed back as H-MEM `helpful` / `wrong` feedback. Every mutation is written
to an append-only JSONL ledger. Embeddings are a dependency-free hashed bag of words; the spec allows any embedder.
Pure standard library, no network.
"""

import hashlib
import json
import math
import re
import uuid
from copy import deepcopy
from pathlib import Path

DAY_MS = 86_400_000
LAYER_WEIGHT = {"long_term": 1.0, "working": 0.8, "short_term": 0.6}
FEEDBACK = {"helpful": (0.05, 1), "not_helpful": (-0.03, 0), "wrong": (-0.20, 0)}
OPPOSITES = [("always", "never"), ("enable", "disable"), ("increase", "decrease"), ("late", "on time"),
             ("supported", "ruled out"), ("yes", "no")]
STOP = set("a an the of to in on for and or is are was were be by with at from this that it as we our".split())
DIM = 256


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9\-]+", text.lower()) if t not in STOP]


def embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for tok in tokens(text):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % DIM] += 1.0 if (h >> 8) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class TrustLedger:
    """Append-only audit ledger (spec §9.1)."""

    ACTIONS = {"create", "read", "update", "delete", "feedback", "promote", "demote", "merge", "conflict_detected",
               "conflict_resolved", "sleep_consolidate", "sleep_archive", "sleep_synthesize", "dream_proposed",
               "dream_approved", "dream_rejected", "restore"}

    def __init__(self, clock, path: Path | None = None):
        self.clock = clock
        self.path = path
        self.entries: list[dict] = []

    def log(self, memory_id: str, action: str, actor: str = "system", previous=None, new=None, **details) -> dict:
        assert action in self.ACTIONS, action
        entry = {"memoryId": memory_id, "action": action, "actor": actor, "timestamp": self.clock(),
                 "previousState": previous, "newState": new, "details": details}
        self.entries.append(entry)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        return entry

    def history(self, memory_id: str) -> list[dict]:
        return [e for e in self.entries if e["memoryId"] == memory_id]


class MemoryStore:
    def __init__(self):
        self._items: dict[str, dict] = {}

    def get(self, memory_id: str):
        return self._items.get(memory_id)

    def all(self) -> list[dict]:
        return list(self._items.values())

    def put(self, record: dict) -> None:
        self._items[record["id"]] = record

    def delete(self, memory_id: str) -> None:
        self._items.pop(memory_id, None)


class SleepCycle:
    """Consolidation and archival (spec §8). Preview never mutates; execute snapshots first."""

    def __init__(self, hmem):
        self.h = hmem
        self.backups: dict[str, list[dict]] = {}

    def _protected(self, m: dict) -> bool:
        referenced = any(m["id"] in (o.get("derivedFrom") or []) or o.get("supersedes") == m["id"]
                         or m["id"] in (o.get("relatedTo") or []) for o in self.h.store.all())
        return bool(m.get("derivedFrom")) or bool(m.get("supersedes")) or referenced or len(m.get("relatedTo") or []) >= 3

    def preview(self) -> dict:
        now = self.h.clock()
        to_archive, to_consolidate = [], []
        for m in self.h.store.all():
            age_days = (now - m["timestamp"]) / DAY_MS
            idle_days = (now - m["lastAccessed"]) / DAY_MS
            if age_days >= 30 and m["accessCount"] <= 2 and not self._protected(m):
                to_archive.append(m["id"])
            elif m["layer"] == "short_term" and idle_days >= 7:
                to_consolidate.append(m["id"])
        return {"toArchive": to_archive, "toConsolidate": to_consolidate, "toSynthesize": []}

    def execute(self, preview: dict) -> dict:
        backup_id = uuid.uuid4().hex
        self.backups[backup_id] = deepcopy(self.h.store.all())
        for mid in preview["toConsolidate"]:
            m = self.h.store.get(mid)
            if m:
                prev = m["layer"]
                m["layer"] = "long_term"
                self.h.ledger.log(mid, "sleep_consolidate", previous={"layer": prev}, new={"layer": "long_term"})
        for mid in preview["toArchive"]:
            m = self.h.store.get(mid)
            if m and not self._protected(m):
                self.h.store.delete(mid)
                self.h.ledger.log(mid, "sleep_archive", previous={"content": m["content"]})
        return {"backupId": backup_id, "archived": len(preview["toArchive"]),
                "consolidated": len(preview["toConsolidate"])}


class Dreaming:
    """Proposals only; nothing materialises until a human approves (spec §7.4)."""

    def __init__(self, hmem):
        self.h = hmem
        self.proposals: dict[str, dict] = {}

    def dream(self) -> list[dict]:
        mems = self.h.store.all()
        out = []
        prefs = [m for m in mems if m["type"] in ("preference", "personal")]
        if len(prefs) >= 2:
            out.append(self._propose("invariant", "Stable pattern: " + "; ".join(m["content"] for m in prefs[:4]),
                                     [m["id"] for m in prefs]))
        for i, a in enumerate(mems):
            cluster = [b for b in mems[i + 1:] if b["type"] not in ("preference", "personal")
                       and self.h.relatedness(a, b) >= 0.35]
            if cluster and a["type"] not in ("preference", "personal"):
                ids = [a["id"]] + [b["id"] for b in cluster]
                out.append(self._propose("insight", f"{len(ids)} related findings: " + a["content"][:120], ids))
        return out

    def _propose(self, kind: str, content: str, source_ids: list[str]) -> dict:
        p = {"id": uuid.uuid4().hex, "kind": kind, "content": content, "derivedFrom": source_ids}
        self.proposals[p["id"]] = p
        self.h.ledger.log(p["id"], "dream_proposed", details_kind=kind)
        return p

    def approve(self, proposal_id: str, actor: str = "human"):
        p = self.proposals.pop(proposal_id, None)
        if not p:
            return None
        rec = self.h.add({"content": p["content"], "source": "dreaming", "layer": "long_term",
                          "type": "preference" if p["kind"] == "invariant" else "factual",
                          "derivedFrom": p["derivedFrom"], "confidence": 0.7})
        self.h.ledger.log(rec["id"], "dream_approved", actor=actor, proposal=proposal_id)
        return rec

    def reject(self, proposal_id: str, actor: str = "human") -> None:
        if self.proposals.pop(proposal_id, None):
            self.h.ledger.log(proposal_id, "dream_rejected", actor=actor)


class ConflictDetector:
    def __init__(self, hmem):
        self.h = hmem

    def scan(self) -> list[dict]:
        found = []
        mems = self.h.store.all()
        for i, a in enumerate(mems):
            for b in mems[i + 1:]:
                if a.get("supersedes") == b["id"] or b.get("supersedes") == a["id"]:
                    continue
                ta, tb = set(tokens(a["content"])), set(tokens(b["content"]))
                for x, y in OPPOSITES:
                    if (x in ta and y in tb) or (y in ta and x in tb):
                        shared = len(ta & tb) / max(1, len(ta | tb))
                        if shared >= 0.4:
                            c = {"a": a["id"], "b": b["id"], "reason": f"opposing '{x}'/'{y}'", "similarity": shared}
                            found.append(c)
                            self.h.ledger.log(a["id"], "conflict_detected", other=b["id"], reason=c["reason"])
                        break
        return found

    def auto_resolve(self, conflict: dict) -> str:
        a, b = self.h.store.get(conflict["a"]), self.h.store.get(conflict["b"])
        score = lambda m: 0.5 * m["confidence"] + 0.2 * min(1, m["accessCount"] / 5) + \
            0.3 * (1.0 if m["source"] == "user_correction" else 0.5)
        sa, sb = score(a), score(b)
        decision_conf = abs(sa - sb) / max(sa, sb, 1e-9)
        if decision_conf < 0.70:
            return "queued"
        winner, loser = (a, b) if sa >= sb else (b, a)
        prev = loser.get("supersededBy")
        loser["supersededBy"] = winner["id"]
        self.h.ledger.log(loser["id"], "conflict_resolved", previous={"supersededBy": prev},
                          new={"supersededBy": winner["id"]})
        return "resolved"

    autoResolve = auto_resolve  # name used by the conformance runner


class HMEM:
    def __init__(self, clock=None, ledger_path: Path | None = None):
        import time
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.store = MemoryStore()
        self.ledger = TrustLedger(self.clock, ledger_path)
        self.sleep = SleepCycle(self)
        self.dreaming = Dreaming(self)
        self.conflicts = ConflictDetector(self)

    # -- writes ---------------------------------------------------------------
    def add(self, rec: dict, actor: str = "system") -> dict:
        source = (rec.get("source") or "").strip()
        if not source:
            raise ValueError("H-MEM rejects a record with no source (spec §2)")
        now = self.clock()
        m = {
            "id": rec.get("id") or uuid.uuid4().hex,
            "content": rec["content"],
            "type": rec.get("type", "factual"),
            "layer": rec.get("layer", "working"),
            "timestamp": now, "lastAccessed": now, "accessCount": 0,
            "tags": list(rec.get("tags") or []),
            "confidence": clamp01(rec.get("confidence", 0.7)),
            "source": source,
            "provenance": rec.get("provenance") or {"origin": source, "learnedAt": now, "label": source},
            "domain": rec.get("domain", "general"),
            "namespace": rec.get("namespace", ""),
            "entities": list(rec.get("entities") or [])[:10],
            "relatedTo": list(rec.get("relatedTo") or [])[:5],
            "supersedes": rec.get("supersedes"),
            "supersededBy": None,
            "derivedFrom": list(rec.get("derivedFrom") or []),
            "embedding": embed(rec["content"]),
        }
        self.store.put(m)
        self.ledger.log(m["id"], "create", actor=actor, new={"confidence": m["confidence"], "content": m["content"]})
        return m

    def feedback(self, memory_id: str, kind: str, actor: str = "human") -> dict:
        m = self.store.get(memory_id)
        if m is None:
            raise KeyError(memory_id)
        delta, access = FEEDBACK[kind]
        prev = m["confidence"]
        m["confidence"] = round(clamp01(prev + delta), 6)
        m["accessCount"] += access
        if kind == "wrong" and "review" not in m["tags"]:
            m["tags"].append("review")
        self.ledger.log(memory_id, "feedback", actor=actor, previous={"confidence": prev},
                        new={"confidence": m["confidence"]}, kind=kind)
        return m

    # -- retrieval (spec §6.1) ---------------------------------------------------
    def relatedness(self, a: dict, b: dict) -> float:
        sem = cosine(a["embedding"], b["embedding"])
        ent = len(set(a["entities"]) & set(b["entities"])) / max(1, len(set(a["entities"]) | set(b["entities"])))
        return 0.6 * sem + 0.3 * ent + 0.1 * (a["domain"] == b["domain"])

    def query(self, text: str, options: dict | None = None, *, entities: list[str] | None = None,
              domain: str | None = None, tags: list[str] | None = None) -> dict:
        opts = {"threshold": 0.35, "topN": 5, **(options or {})}
        now = self.clock()
        q_emb = embed(text)
        q_tokens = tokens(text)[:8]
        q_ents = set(entities or [])
        q_tags = set(tags or [])
        scored = []
        for m in self.store.all():
            m_tokens = set(tokens(m["content"]))
            semantic = max(0.0, cosine(q_emb, m["embedding"]))
            keyword = len(set(q_tokens) & m_tokens) / max(1, len(set(q_tokens) | m_tokens))
            tag = len(q_tags & set(m["tags"])) / max(1, len(q_tags)) if q_tags else 0.0
            dom = 1.0 if domain and m["domain"] == domain else 0.0
            ent = len(q_ents & set(m["entities"])) / max(1, len(q_ents)) if q_ents else 0.0
            layer = LAYER_WEIGHT.get(m["layer"], 0.6)
            recency = math.exp(-((now - m["lastAccessed"]) / DAY_MS) / 14.0)
            superseded = 1.0 if m.get("supersededBy") else 0.0
            raw = (0.35 * semantic + 0.20 * keyword + 0.10 * tag + 0.10 * dom + 0.15 * ent
                   + 0.05 * layer + 0.05 * recency - 0.20 * superseded)
            score = clamp01(raw) * m["confidence"]
            if score >= opts["threshold"]:
                scored.append({"memory": m, "score": round(score, 4),
                               "parts": {"semantic": round(semantic, 3), "keyword": round(keyword, 3),
                                         "entity": round(ent, 3), "superseded": superseded}})
        scored.sort(key=lambda s: s["score"], reverse=True)
        top = scored[: opts["topN"]]
        for s in top:
            s["memory"]["lastAccessed"] = now
            s["memory"]["accessCount"] += 1
            self.ledger.log(s["memory"]["id"], "read", score=s["score"])
        return {"memories": top, "retrievalReason": f"hybrid score >= {opts['threshold']}", "strategy": "minimal"}

    def context_block(self, result: dict) -> str:
        """Reinjection format (spec §6.2): domain-grouped lines with layer markers."""
        lines = []
        for s in result["memories"]:
            m = s["memory"]
            lines.append(f"[{m['domain']}|{m['layer']}|conf {m['confidence']:.2f}] {m['content']} (source: {m['source']})")
        return "\n".join(lines)

    # -- persistence -------------------------------------------------------------
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [{k: v for k, v in m.items() if k != "embedding"} for m in self.store.all()]
        path.write_text(json.dumps(records, indent=1, default=str), encoding="utf-8")

    def load(self, path: Path) -> None:
        if not path.exists():
            return
        for m in json.loads(path.read_text(encoding="utf-8")):
            m["embedding"] = embed(m["content"])
            self.store.put(m)


# ---------------------------------------------------------------------------
# StockWhy case memory
# ---------------------------------------------------------------------------

DECISIONS = {"approve": ("helpful", "approved"), "reject": ("wrong", "rejected")}


class CaseMemory:
    """
    Persistent H-MEM case memory for StockWhy findings.

        recall(facility_id, commodity, limit=5) -> prior findings, newest first
        store(finding, citations, run_id)       -> memory id (status "pending_approval")
        feedback(memory_id, "approve"|"reject", note="") -> updated finding

    Records live in `path` (JSON); the append-only audit ledger sits next to it as `<stem>.ledger.jsonl`.
    """

    def __init__(self, path: str | Path = "logs/memory/hmem.json", clock=None):
        self.path = Path(path)
        self.ledger_path = self.path.with_name(self.path.stem + ".ledger.jsonl")
        self.h = HMEM(clock=clock, ledger_path=self.ledger_path)
        self.h.load(self.path)

    # -- writes -------------------------------------------------------------------
    def store(self, finding: dict, citations: list, run_id: str) -> str:
        """Store a finding as a pending memory. `finding` needs facility_id, commodity, month and a cause."""
        finding = dict(finding or {})
        facility = str(finding.get("facility_id") or "").strip()
        commodity = str(finding.get("commodity") or "").strip()
        month = str(finding.get("month") or "").strip()
        cause = str(finding.get("cause") or finding.get("hypothesis_id") or finding.get("top_cause")
                    or finding.get("primary_cause") or "").strip()
        summary = str(finding.get("summary") or finding.get("explanation") or finding.get("reason") or "").strip()
        citations = [str(c) for c in (citations or []) if str(c).strip()]
        run_id = str(run_id or "").strip()
        if not (facility and commodity and month and cause):
            raise ValueError("a finding needs facility_id, commodity, month and cause")
        if not run_id:
            raise ValueError("H-MEM rejects a memory with no source: run_id is required")
        if not citations:
            raise ValueError("a finding without cited evidence rows is not stored")

        now = self.h.clock()
        confidence = finding.get("confidence")
        confidence = float(confidence) if isinstance(confidence, (int, float)) and 0 <= confidence <= 1 else 0.6
        content = f"{facility} {commodity} {month}: {cause}. {summary}".strip()
        m = self.h.add({
            "content": content,
            "source": f"stockwhy-run:{run_id}",
            "type": "factual",
            "layer": "working",
            "domain": "stockout",
            "namespace": f"{facility}|{commodity}",
            "entities": [facility, commodity, month, cause],
            "tags": ["pending_approval", cause],
            "confidence": confidence,
            "provenance": {"origin": "stockwhy", "run_id": run_id, "citations": citations, "learnedAt": now,
                           "label": f"StockWhy run {run_id}"},
        })
        m.update({"facility_id": facility, "commodity": commodity, "month": month, "cause": cause,
                  "summary": summary, "citations": citations, "status": "pending_approval"})
        self._save()
        return m["id"]

    def feedback(self, memory_id: str, decision: str, note: str = "") -> dict:
        """Record the pharmacist's decision: approve -> H-MEM `helpful`, reject -> `wrong` (adds review tag)."""
        if decision not in DECISIONS:
            raise ValueError(f"decision must be 'approve' or 'reject', not {decision!r}")
        m = self.h.store.get(memory_id)
        if m is None:
            raise KeyError(memory_id)
        kind, status = DECISIONS[decision]
        self.h.feedback(memory_id, kind, actor="pharmacist")
        previous = m.get("status")
        m["status"] = status
        m["tags"] = [t for t in m["tags"] if t not in ("pending_approval", "approved", "rejected")] + [status]
        if note:
            m["note"] = note
        self.h.ledger.log(memory_id, "update", actor="pharmacist", previous={"status": previous},
                          new={"status": status}, decision=decision, note=note)
        self._save()
        return self._view(m)

    # -- reads -------------------------------------------------------------------
    def recall(self, facility_id: str, commodity: str, limit: int = 5) -> list:
        """Prior findings for this facility and medicine, newest month first (ties: most recently stored)."""
        namespace = f"{facility_id}|{commodity}"
        hits = [m for m in self.h.store.all() if m.get("namespace") == namespace and m.get("cause")]
        hits.sort(key=lambda m: (m.get("month", ""), m["timestamp"]), reverse=True)
        hits = hits[: max(0, int(limit))]
        now = self.h.clock()
        for m in hits:
            m["lastAccessed"] = now
            m["accessCount"] += 1
            self.h.ledger.log(m["id"], "read", actor="stockwhy", reason="recall")
        if hits:
            self._save()
        return [self._view(m) for m in hits]

    def get(self, memory_id: str) -> dict | None:
        m = self.h.store.get(memory_id)
        return self._view(m) if m else None

    def ledger(self, memory_id: str | None = None) -> list:
        """Ledger entries from disk (all processes), optionally for one memory."""
        if not self.ledger_path.exists():
            return []
        entries = [json.loads(line) for line in self.ledger_path.read_text(encoding="utf-8").splitlines() if line]
        return [e for e in entries if memory_id is None or e["memoryId"] == memory_id]

    # -- internals -----------------------------------------------------------------
    @staticmethod
    def _view(m: dict) -> dict:
        return {"id": m["id"], "facility_id": m.get("facility_id"), "commodity": m.get("commodity"),
                "month": m.get("month"), "cause": m.get("cause"), "summary": m.get("summary", ""),
                "citations": list(m.get("citations") or []), "status": m.get("status"),
                "confidence": m["confidence"], "note": m.get("note", ""), "provenance": m.get("provenance"),
                "stored_at": m["timestamp"]}

    def _save(self) -> None:
        self.h.save(self.path)
