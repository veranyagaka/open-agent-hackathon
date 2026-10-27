"""
engines/scout_intent.py

Scout Intent (Meterless engine), a Python port of the spec at
https://github.com/meterless/meterless/blob/main/engines/scout-intent/AGENTS.md (Apache-2.0).

In StockWhy it runs before anything acts:
  Sense (Stage-1 lexical scoring, canonical bands) -> Interpret (bind facility, medicine and month to
  values that exist in the data) -> Guard (prompt injection, secret exfiltration, role) -> Route
  (capability graph) -> a signed, expiring Contract.
Every agent step checks the contract for the capability it needs. There is deliberately no capability for
`order.send`, so StockWhy can draft an order for a pharmacist but can never send one.

Stage 2 (semantic rescoring) is not implemented; the spec makes it optional and Stage 1 stands alone.
Pure standard library, no network.

Interface:
    gate(request, dataset=None) -> {"decision", "intent", "band", "reason", "contract", "trace", ...}
    Contract.check(capability), Contract.child(intent, capabilities), Contract.to_dict()
"""

import calendar
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from difflib import get_close_matches
from pathlib import Path

BANDS = [(0.80, "high"), (0.55, "medium"), (0.40, "low"), (0.0, "reject")]
# Every contract lives 5 minutes. A long run does not extend it: the orchestrator
# issues a fresh child contract per phase (parentId = the original contract).
TTL = timedelta(minutes=5)
POLICY_PACK = "stockwhy-default-2"
REGISTRY_PATH = Path(__file__).with_name("intents.json")

# Capability graph: abstract capability -> the StockWhy component that exercises it.
# `order.send` and `clinical.advise` are intentionally absent: intents that need them are refused.
CAPABILITY_GRAPH = {
    "data.read": "tools.data_loader (CSV or Zetaris)",
    "llm.call": "llm_client (Nightshift)",
    "memory.read": "engines.hmem.CaseMemory.recall",
    "memory.write": "engines.hmem.CaseMemory.store",
    "action.draft": "agents.action_strategist (drafts for pharmacist approval)",
}
EXPLAIN_CAPABILITIES = frozenset({"data.read", "llm.call", "memory.read", "memory.write"})

INJECTION_PATTERNS = [
    (r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|earlier|all)\b.{0,30}"
     r"\b(instructions?|rules?|prompts?|guidelines?)\b", "instruction-override"),
    (r"\b(ignore|disregard|forget)\s+(all\s+)?(previous|prior|above|earlier)\b", "instruction-override"),
    (r"\b(disregard|ignore)\s+the\s+(user|system|rules)", "instruction-override"),
    (r"\byou are now\b|\bunrestricted mode\b|\bjailbreak\b|\bdeveloper mode\b", "role-drift"),
    (r"</?\s*(system|user|assistant)\s*>|\[/?INST\]|<\|im_(start|end)\|>", "role-confusion"),
    (r"\bpretend to be\b|\bact as (the )?(system|admin)", "role-confusion"),
    (r"\b(reveal|show|print|dump|leak|tell me|give me|send me|what is|what's)\b.{0,30}"
     r"\b(api[ _-]?keys?|credentials?|passwords?|secrets?|tokens?|system prompt|signing key)", "exfiltration"),
    (r"\b[a-z0-9]+_(api_key|secret|secret_key|token|signing_key|password)\b", "exfiltration"),
    (r"(^|[\s/'\"`])\.env\b|\benvironment variables?\b|\benv vars?\b|\bsystem prompt\b", "exfiltration"),
    (r"\b(grant|give)\b.{0,20}\badmin\b|\binternal_admin\w*|\bdrop\s+(the\s+)?\w+\s+table\b|\bdelete\s+all\b",
     "out-of-band-tool"),
    (r"\banswer_key\b|eval/answer", "evaluation-leak"),
    (r"\b(ignore|disregard|forget)\b.{0,20}\b(everything|anything|all)\b.{0,30}"
     r"\b(said|told|written|above|before|earlier|so far)\b", "instruction-override"),
    (r"\b(hidden|secret|system|internal)\s+(instructions?|prompts?|rules|directives?)\b", "exfiltration"),
    (r"\bnew\s+(task|instructions?|role)\s*:", "instruction-override"),
    (r"\bdo anything now\b", "role-drift"),
    # Swahili: "puuza ... maagizo" (ignore ... instructions), "ufunguo" (key)
    (r"\bpuuza\b.{0,60}\bmaagizo\b", "instruction-override"),
    (r"\bufunguo\b", "exfiltration"),
]
# Case-sensitive: "DAN" jailbreak persona (lower-case "dan" is a name).
CASE_SENSITIVE_PATTERNS = [(r"\bDAN\b", "role-drift")]
# "i g n o r e  a l l" -> "ignore all": collapse runs of single letters split by single spaces.
SPACED_LETTERS = re.compile(r"\b(?:\w[ .\-_]){3,}\w\b")
CONTROL_CHARS = re.compile(r"[‪-‮⁦-⁩​-‏]|\\u202[a-e]", re.I)
PII_PATTERNS = [(r"\b(?:\+?254|0)7\d{8}\b", "phone"), (r"\b\d{8}\b", "national-id")]

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS.update({m: i for i, m in enumerate(["", "januari", "februari", "machi", "aprili", "mei", "juni", "julai",
                                           "agosti", "septemba", "oktoba", "novemba", "desemba"]) if m})
COMMODITY_ALIASES = {
    "oxytocin": "oxytocin", "ors": "ORS", "oral rehydration": "ORS", "zinc": "zinc", "iron": "iron-folate",
    "folate": "iron-folate", "ifas": "iron-folate", "amoxicillin": "amoxicillin", "amox": "amoxicillin",
    "magnesium": "magnesium", "mgso4": "magnesium",
}

_env_key = os.environ.get("SCOUT_SIGNING_KEY")
_SIGNING_KEY = _env_key.encode() if _env_key else secrets.token_bytes(32)
del _env_key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def band_for(score: float) -> str:
    for floor, name in BANDS:
        if score >= floor:
            return name
    return "reject"


def scan_injection(text: str) -> list:
    """Injection kinds found in any text (a question, or data values that will reach a model prompt)."""
    if not text:
        return []
    kinds = ["control-bytes"] if CONTROL_CHARS.search(text) else []
    normalised = unicodedata.normalize("NFKC", text)
    collapsed = SPACED_LETTERS.sub(lambda m: re.sub(r"[ .\-_]", "", m.group(0)), normalised)
    variants = [normalised] if collapsed == normalised else [normalised, collapsed]
    for variant in variants:
        kinds += [kind for pattern, kind in INJECTION_PATTERNS if re.search(pattern, variant, re.I | re.S)]
        kinds += [kind for pattern, kind in CASE_SENSITIVE_PATTERNS if re.search(pattern, variant)]
    if re.search(r"\b(note to|attention) (the )?(assistant|ai|model)\b|\bassistant\s*:", normalised, re.I):
        kinds.append("addressed-to-model")
    return list(dict.fromkeys(kinds))


def scan_pii(text: str) -> list:
    return [kind for pattern, kind in PII_PATTERNS if text and re.search(pattern, text)]


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    reg = json.loads(Path(path).read_text(encoding="utf-8"))
    intents = {i["id"]: i for i in reg["intents"]}
    for intent in intents.values():
        if not intent.get("examples"):
            raise ValueError(f"intent {intent['id']} has no examples (spec: examples are mandatory)")
    return {"version": reg["registryVersion"], "intents": intents}


REGISTRY = load_registry()


def classify(text: str) -> list:
    """Stage-1 lexical scoring: each intent's share of matched trigger weight, damped when evidence is thin."""
    low = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    raw = {}
    for iid, intent in REGISTRY["intents"].items():
        hits = [(t, w) for t, w in intent.get("triggers", {}).items() if t in low]
        raw[iid] = {"weight": sum(w for _, w in hits), "spans": [t for t, _ in hits]}
    total = sum(r["weight"] for r in raw.values())
    cands = []
    for iid, r in raw.items():
        score = (r["weight"] / total) * min(1.0, r["weight"] / 4) if total else 0.0
        cands.append({"intent": iid, "score": round(score, 3), "weight": r["weight"], "spans": r["spans"]})
    cands.sort(key=lambda c: c["score"], reverse=True)
    return cands


def known_entities(dataset: dict) -> dict:
    """Facilities, commodities and months that exist in a load_dataset() result (DataFrames) or a ready dict."""
    if all(k in dataset for k in ("facilities", "commodities", "months")) and "stock" not in dataset:
        return {k: sorted({str(v) for v in dataset[k]}) for k in ("facilities", "commodities", "months")}
    stock = dataset["stock"]
    facilities = set(str(v) for v in stock["facility_id"])
    fac_table = dataset.get("facilities")
    if fac_table is not None and hasattr(fac_table, "columns") and "facility_id" in fac_table.columns:
        facilities |= set(str(v) for v in fac_table["facility_id"])
    return {
        "facilities": sorted(f for f in facilities if f and f != "nan"),
        "commodities": sorted({str(v) for v in stock["commodity"] if str(v) not in ("", "nan")}),
        "months": sorted({str(v) for v in stock["month"] if str(v) not in ("", "nan")}),
    }


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

class ContractViolation(Exception):
    """Raised when a step acts outside its contract: unsigned, tampered, expired, or capability not granted."""


class Contract:
    """HMAC-signed, expiring grant of capabilities for one intent (spec: ExecutionContract)."""

    def __init__(self, id: str, intent: str, capabilities, expires_at: datetime, parent_id: str | None = None,
                 issued_at: datetime | None = None, params: dict | None = None, role: str = "viewer",
                 trace_id: str | None = None, approvals: list | None = None, signature: str = ""):
        self.id = id
        self.intent = intent
        self.capabilities = set(capabilities)
        self.expires_at = expires_at
        self.parent_id = parent_id
        self.issued_at = issued_at or datetime.now(timezone.utc)
        self.params = dict(params or {})
        self.role = role
        self.trace_id = trace_id or uuid.uuid4().hex
        self.approvals = list(approvals or [])
        self.signature = signature

    @classmethod
    def issue(cls, intent: str, capabilities, params: dict | None = None, role: str = "viewer",
              parent_id: str | None = None, trace_id: str | None = None, ttl: timedelta | None = None) -> "Contract":
        unknown = set(capabilities) - set(CAPABILITY_GRAPH)
        if unknown:
            raise ContractViolation(f"no tool for capability {sorted(unknown)}; StockWhy cannot grant it")
        now = datetime.now(timezone.utc)
        approvals = ["pharmacist-confirm"] if "action.draft" in capabilities else []
        c = cls(id=f"{int(now.timestamp() * 1000):013d}-{uuid.uuid4().hex[:10]}", intent=intent,
                capabilities=capabilities, expires_at=now + (TTL if ttl is None else ttl), parent_id=parent_id,
                issued_at=now, params=params, role=role, trace_id=trace_id, approvals=approvals)
        c.signature = c._sign()
        return c

    def _body(self) -> dict:
        return {
            "id": self.id, "intent": self.intent, "capabilities": sorted(self.capabilities),
            "expires_at": self.expires_at.isoformat(), "issued_at": self.issued_at.isoformat(),
            "parent_id": self.parent_id, "params": self.params, "role": self.role, "trace_id": self.trace_id,
            "approvals": self.approvals, "registry_version": REGISTRY["version"], "policy_pack": POLICY_PACK,
        }

    def _sign(self) -> str:
        return hmac.new(_SIGNING_KEY, canonical_json(self._body()).encode(), hashlib.sha256).hexdigest()

    def verify(self, now: datetime | None = None) -> None:
        if not self.signature:
            raise ContractViolation("unsigned contract")
        if not hmac.compare_digest(self._sign(), self.signature):
            raise ContractViolation("contract signature does not match (tampered or wrong key)")
        if (now or datetime.now(timezone.utc)) >= self.expires_at:
            raise ContractViolation(f"contract {self.id} expired; run Scout again")

    def check(self, capability: str, now: datetime | None = None) -> None:
        """Raise ContractViolation unless this contract is valid and grants `capability`."""
        self.verify(now)
        if capability not in self.capabilities:
            raise ContractViolation(f"capability '{capability}' is not granted by contract {self.id} "
                                    f"(intent {self.intent})")

    def child(self, intent: str, capabilities, parent_id: str | None = None) -> "Contract":
        """
        Re-plan: a signed child contract (same trace) for a follow-on intent or phase.
        parent_id defaults to this contract's id; a phase contract issued from the
        previous phase passes the original contract's id so every phase points at it.
        """
        self.verify()
        capabilities = set(capabilities)
        registered = REGISTRY["intents"].get(intent)
        if registered is None:
            raise ContractViolation(f"unknown intent '{intent}'")
        outside = capabilities - set(registered["capabilities"])
        if outside:
            raise ContractViolation(f"intent '{intent}' does not allow {sorted(outside)}")
        return Contract.issue(intent, capabilities, params=self.params, role=self.role,
                              parent_id=parent_id or self.id, trace_id=self.trace_id)

    def to_dict(self) -> dict:
        """Spec field names (ExecutionContract). The signature is HMAC-SHA256 over the canonical JSON body."""
        flags = sorted(c for c in self.capabilities if c in ("action.draft", "memory.write"))
        return {
            "contractId": self.id,
            "parentId": self.parent_id,
            "traceId": self.trace_id,
            "intent": self.intent,
            "risk": {"level": "medium" if "action.draft" in self.capabilities else "low",
                     "flags": flags, "approvals": list(self.approvals)},
            "scope": {"capabilities": sorted(self.capabilities), "params": dict(self.params),
                      "role": self.role},
            "issuedAt": self.issued_at.isoformat(),
            "expiresAt": self.expires_at.isoformat(),
            "registryVersion": REGISTRY["version"],
            "policyPackVersion": POLICY_PACK,
            "signature": self.signature,
            "signedBy": "scout",
        }

    def __repr__(self) -> str:
        return f"Contract(id={self.id!r}, intent={self.intent!r}, capabilities={sorted(self.capabilities)})"


# ---------------------------------------------------------------------------
# Interpret: bind facility, commodity and month
# ---------------------------------------------------------------------------

def _norm_facility(text: str) -> str | None:
    m = re.search(r"\bfac(?:ility)?[-\s_]*(?:no\.?\s*)?(\d{1,3})\b", text, re.I) or re.fullmatch(r"\s*(\d{1,3})\s*", text)
    return f"FAC-{int(m.group(1)):03d}" if m else None


def _norm_month(text: str, known_months: list | None) -> tuple:
    """Returns (month or None, note). Accepts 2026-03, 2026-3, 'March 2026', 'Machi 2026', or 'March' alone."""
    low = text.lower()
    m = re.search(r"\b(20\d\d)-(\d{1,2})\b", low)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}", None
    for name, num in sorted(MONTHS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{name}\b", low):
            year = re.search(r"\b(20\d\d)\b", low)
            if year:
                return f"{year.group(1)}-{num:02d}", None
            options = [k for k in (known_months or []) if int(k[5:7]) == num]
            if options:
                return max(options), f"no year given; used {max(options)}, the latest in the data"
            return None, None
    return None, None


def _bind_commodity(text: str, commodities: list | None) -> tuple:
    """Returns (commodity or None, note, suggestions)."""
    low = text.lower().strip()
    if not commodities:
        return (text.strip() or None), None, []
    for c in commodities:
        if c.lower() == low or c.lower() in low:
            return c, None, []
    for alias, stem in COMMODITY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", low):
            matches = [c for c in commodities if stem.lower() in c.lower()]
            if len(matches) == 1:
                return matches[0], f"interpreted '{alias}' as {matches[0]}", []
            if matches:
                return None, None, matches
    words = re.findall(r"[a-z\-]{4,}", low)
    stems = [c.split()[0].lower() for c in commodities]
    for w in words:
        hit = get_close_matches(w, stems, n=1, cutoff=0.75)
        if hit:
            return None, None, [c for c in commodities if c.lower().startswith(hit[0])]
    return None, None, []


def bind(request: dict, known: dict | None) -> dict:
    """Bind the request to real values. Structured fields win; the free-text question fills gaps."""
    question = str(request.get("question") or "")
    params, notes, problems, suggestions, bad = {}, [], [], {}, set()

    raw_fac = str(request.get("facility_id") or "").strip()
    fac = _norm_facility(raw_fac) if raw_fac else _norm_facility(question)
    if raw_fac and fac is None:
        problems.append(f"'{raw_fac}' is not a facility ID (expected e.g. FAC-016)")
        bad.add("facility_id")
    elif fac:
        if known and fac not in known["facilities"]:
            close = get_close_matches(fac, known["facilities"], n=3, cutoff=0.6)
            problems.append(f"facility {fac} is not in the data")
            bad.add("facility_id")
            suggestions["facility_id"] = close
        else:
            params["facility_id"] = fac
            if raw_fac and raw_fac != fac:
                notes.append(f"interpreted '{raw_fac}' as {fac}")

    raw_com = str(request.get("commodity") or "").strip()
    com_src = raw_com or question
    if com_src:
        com, note, close = _bind_commodity(com_src, known["commodities"] if known else None)
        if not known and not raw_com:
            com = None  # without data, free text cannot be trusted as a commodity name
            for alias in COMMODITY_ALIASES:
                if re.search(rf"\b{re.escape(alias)}\b", question.lower()):
                    com = alias
                    break
        if com:
            params["commodity"] = com
            if note:
                notes.append(note)
        elif raw_com:
            problems.append(f"medicine '{raw_com}' is not in the data")
            bad.add("commodity")
            if close:
                suggestions["commodity"] = close
        elif close:
            suggestions["commodity"] = close

    raw_month = str(request.get("month") or "").strip()
    months = known["months"] if known else None
    month, note = _norm_month(raw_month or question, months)
    if raw_month and month is None:
        problems.append(f"'{raw_month}' is not a month (expected YYYY-MM)")
        bad.add("month")
    elif month:
        if months and month not in months:
            problems.append(f"month {month} is outside the data ({months[0]} to {months[-1]})")
            bad.add("month")
            suggestions["month"] = [months[-1]]
        else:
            params["month"] = month
            if note:
                notes.append(note)
            elif raw_month and raw_month != month:
                notes.append(f"interpreted '{raw_month}' as {month}")

    missing = [p for p in ("facility_id", "commodity", "month") if p not in params and p not in bad]
    return {"params": params, "missing": missing, "problems": problems, "interpretations": notes,
            "suggestions": suggestions}


def _clarify_question(missing: list, problems: list, suggestions: dict, known: dict | None) -> str:
    asks = {"facility_id": "a facility ID such as FAC-016",
            "commodity": ("one of: " + ", ".join(known["commodities"])) if known else "the medicine",
            "month": (f"a month between {known['months'][0]} and {known['months'][-1]}" if known and known["months"]
                      else "a month as YYYY-MM")}
    parts = problems + [asks[m] for m in missing]
    text = "To investigate I need: " + "; ".join(parts) + "."
    for field, opts in suggestions.items():
        if opts:
            text += f" Did you mean {' or '.join(opts)} for {field.replace('_id', '')}?"
    return text


# ---------------------------------------------------------------------------
# Gate (the full Scout pipeline)
# ---------------------------------------------------------------------------

def _result(decision, intent, band, reason, trace, contract=None, **extra) -> dict:
    out = {"decision": decision, "intent": intent, "band": band if band != "reject" else "low",
           "reason": reason, "contract": contract, "trace": trace}
    out.update(extra)
    return out


def gate(request: dict, dataset: dict | None = None) -> dict:
    """
    Decide whether StockWhy may act on a request, and with which capabilities.

    request: {"question": str (optional), "facility_id", "commodity", "month", "role": "pharmacist"|"viewer"|...}
    dataset: a load_dataset() result (or {"facilities", "commodities", "months"}); when given, values are bound
             to what actually exists in the data.
    Returns {"decision": "allow"|"clarify"|"refuse"|"block", "intent", "band", "reason", "contract", "trace",
             "params", "suggestions"}.
    """
    t0 = time.perf_counter()
    request = dict(request or {})
    question = str(request.get("question") or "")
    role = str(request.get("role") or "viewer").strip().lower()
    trace = {"engine": "scout-intent", "trace_id": uuid.uuid4().hex, "registry_version": REGISTRY["version"],
             "policy_pack": POLICY_PACK, "stage2": "skipped", "role": role, "question_chars": len(question)}

    def done(*args, **kw):
        trace["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        kw.setdefault("params", {})
        kw.setdefault("suggestions", {})
        return _result(*args, trace=trace, **kw)

    # Guard first: every string field can carry an injection, not only the question.
    flags = []
    for field in ("question", "facility_id", "commodity", "month", "role"):
        for kind in scan_injection(str(request.get(field) or "")):
            flags.append({"layer": "injection", "field": field, "kind": kind})
    trace["guard"] = {"flags": flags, "pii": scan_pii(question)}

    # Sense
    if question.strip():
        cands = classify(question)
        top = cands[0]
        band = band_for(top["score"])
        trace["candidates"] = [{k: c[k] for k in ("intent", "score", "spans")} for c in cands[:3]]
    else:
        cands, top, band = [], {"intent": "stockout.explain", "score": 1.0}, "high"
        trace["candidates"] = [{"intent": "stockout.explain", "score": 1.0, "spans": ["structured request"]}]
    trace["band"] = band

    if flags:
        kinds = ", ".join(dict.fromkeys(f["kind"] for f in flags))
        return done("block", top["intent"] if band != "reject" else "GENERAL", "high",
                    f"Blocked by Scout guard ({kinds}). StockWhy will not follow instructions embedded in a request "
                    "or reveal keys, prompts or configuration.")

    # Route: refuse at the boundary anything StockWhy has no capability for.
    by_id = {c["intent"]: c for c in cands}
    order = by_id.get("order.submit")
    if order and (top["intent"] == "order.submit" or order["weight"] >= 4):
        return done("refuse", "order.submit", band,
                    "StockWhy cannot send or place orders (no capability 'order.send' exists). It drafts actions "
                    "for a pharmacist to approve and send through the normal channel.")
    if top["intent"] == "clinical.advice" and band != "reject":
        return done("refuse", "clinical.advice", band,
                    "StockWhy explains medicine supply, not dosing or treatment. Ask a clinician or check the "
                    "national treatment guidelines.")

    intent_id = top["intent"] if band != "reject" else "GENERAL"
    if intent_id == "action.draft":
        trace["requested_intent"] = "action.draft"  # drafting follows an explanation; the run starts there
        intent_id = "stockout.explain"
    intent = REGISTRY["intents"][intent_id]

    if intent["roles"] != ["*"] and role not in intent["roles"]:
        return done("refuse", intent_id, band, f"role '{role}' may not use {intent_id}.")

    known = known_entities(dataset) if dataset is not None else None
    binding = bind(request, known)
    trace["binding"] = {k: binding[k] for k in ("params", "missing", "problems", "interpretations")}

    if intent_id == "GENERAL":
        if binding["params"] or any(request.get(f) for f in ("facility_id", "commodity", "month")):
            # Entities but no stock-out wording: confirm instead of guessing.
            p = binding["params"]
            guess = (f"why did {p.get('facility_id', 'the facility')} run out of {p.get('commodity', 'the medicine')}"
                     f" in {p.get('month', 'the month')}?")
            return done("clarify", "stockout.explain", "low", f"Did you mean: {guess}",
                        params=binding["params"], suggestions=binding["suggestions"])
        return done("refuse", "GENERAL", band,
                    "Out of scope. StockWhy explains medicine stock-outs and drafts actions for a pharmacist, "
                    "for example: 'Why did FAC-016 run out of oxytocin in March 2026?'")

    if band == "low":
        return done("clarify", intent_id, band,
                    "Not sure what you are asking. Do you want the cause of a stock-out (facility, medicine, month)?",
                    params=binding["params"], suggestions=binding["suggestions"])
    if binding["missing"] or binding["problems"]:
        return done("clarify", intent_id, band,
                    _clarify_question(binding["missing"], binding["problems"], binding["suggestions"], known),
                    params=binding["params"], suggestions=binding["suggestions"])

    if band == "high" and binding["interpretations"]:
        band = "medium"  # we corrected the user's wording; say so, and do not claim high confidence
    contract = Contract.issue("stockout.explain", EXPLAIN_CAPABILITIES, params=binding["params"], role=role,
                              trace_id=trace["trace_id"])
    trace["contract_id"] = contract.id
    reason = "Bound to " + ", ".join(f"{k}={v}" for k, v in binding["params"].items())
    if binding["interpretations"]:
        reason += " (" + "; ".join(binding["interpretations"]) + ")"
    return done("allow", "stockout.explain", band, reason, contract=contract, params=binding["params"])
