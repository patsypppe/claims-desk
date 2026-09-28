"""Final defensive check on every reply, based on authorization and provenance (not a keyword blacklist).

Before verification: the reply may contain NO claim-specific atoms at all (real or invented).
After verification: every claim-specific atom must come from a fact authorized for this turn.
Deliberately independent from evals/leak_detector.py so one can catch the other's blind spots.
"""
import re
from decimal import Decimal, InvalidOperation

from claims_agent.domain.models import FrozenModel
from claims_agent.domain.repository import FixtureRepository
from claims_agent.grounding.followup import DOC_ALIASES
from claims_agent.normalize import MONTH_ALT, month_number, normalize_claim_id, unify_dashes
from claims_agent.response.context import ResponseContext

STATUS_WORDS = ("denied", "denial", "approved", "closed", "settled", "open", "pending", "paid", "rejected")
STRONG_STATUS = ("denied", "denial", "approved", "settled", "paid", "rejected")
CLAIM_REF = re.compile(r"\b(claim|case|cl[-\s]?\d{4})", re.I)
VERIFIED_CLAIM = re.compile(r"(?<!once )(?<!until )(?<!after )(?<!when )(?<!before )(?<!if )"
                            r"\byou(?:'re| are)\s+(?:now\s+)?(?:fully\s+)?verified\b", re.I)
ACTION_CLAIMS = {
    "tool.send_summary_email.result": re.compile(r"\bemailed\b|\bsent\b[^.!?]{0,40}\b(summary|e-?mail)\b|"
                                                 r"\b(summary|e-?mail)\b[^.!?]{0,30}\b(has been|was|is) sent\b", re.I),
    "tool.escalate_to_human.ticket": re.compile(r"\b(i'?ve|i have|has been|was)\s+(escalated|transferred)\b", re.I),
}


# When the deadline on file has passed, any wording that presents appeal time as still available is ungrounded.
LIVE_DEADLINE_RE = re.compile(r"(still have \d+|\d+ (?:more )?days? (?:left|remaining|to appeal)|you have until|"
                              r"(?:can|could|are able to) still (?:appeal|submit|file)|still (?:time|eligible|open) to|"
                              r"deadline is (?:next|in \d|tomorrow|this|coming)|\buntil " + MONTH_ALT + r")", re.I)


class ValidationResult(FrozenModel):
    ok: bool
    violations: tuple[str, ...] = ()


def _ngrams(text: str, n: int = 4) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z]+", text.lower())
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def _amounts(text: str) -> set[str]:
    found = set()
    for m in re.finditer(r"(\$\s?)(\d{1,3}(?:,\d{3})+|\d+)(\.\d{2})?|\b(\d{1,3}(?:,\d{3})*|\d+)\.(\d{2})\b|"
                         r"\b(\d[\d,]*)\s*(?:dollars|usd)\b|\busd\s*\d[\d,]*(?:\.\d{2})?|\b\d{1,3}(?:,\d{3})+\b",
                         text, re.I):
        raw = m.group(0).replace("$", "").replace(",", "").lower().replace("dollars", "").replace("usd", "").strip()
        try:
            found.add(f"{Decimal(raw):.2f}")
        except InvalidOperation:
            continue
    return found


def _dates(text: str) -> set[str]:
    found = {f"{int(y):04d}-{int(m):02d}-{int(d):02d}" for y, m, d in re.findall(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text)}
    found |= {f"md:{int(m)}-{int(d)}" for m, d, _ in re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text)}
    for mon, day in re.findall(MONTH_ALT + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", text, re.I):
        found.add(f"md:{month_number(mon)}-{int(day)}")
    for day, mon in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + MONTH_ALT, text, re.I):
        found.add(f"md:{month_number(mon)}-{int(day)}")
    for mon, year in re.findall(MONTH_ALT + r"\.?,?\s+(\d{4})\b", text, re.I):
        found.add(f"my:{year}-{month_number(mon):02d}")
    return found


def _date_keys(text: str) -> set[str]:
    keys = _dates(text)
    full = [k for k in keys if not k.startswith(("md:", "my:"))]
    return keys | {f"md:{int(k[5:7])}-{int(k[8:10])}" for k in full} | {f"my:{k[:7]}" for k in full}


class ResponseValidator:
    def __init__(self, repo: FixtureRepository, pii_scanner=None) -> None:
        self._repo = repo
        self._scanner = pii_scanner
        self._documents = sorted({d.lower() for c in repo.claims for d in c.documents_needed}
                                 | {k.lower() for k in DOC_ALIASES} | {k.lower() for k in repo.guideline.document_guidance},
                                 key=len, reverse=True)
        self._phrases = {c.case_id: [p for p in (c.denial_reason, c.summary) if p] for c in repo.claims}
        self._owner = {c.case_id: c.party_id for c in repo.claims}
        self._names = {p.party_id: [n.lower() for n in (p.name, *p.name_aliases)] for p in repo.policyholders}
        self._pii = {p.party_id: {p.id_last4, p.phone[-4:], p.email.lower(), *(a.lower() for a in p.email_aliases)}
                     for p in repo.policyholders}

    def _atoms(self, text: str, strict: bool = False) -> set[str]:
        text = unify_dashes(text)
        low = text.lower()
        atoms = {f"claim:{normalize_claim_id(m)}" for m in re.findall(r"\bc\s*\.?\s*l[\s-]*\d{4}\b", text, re.I)}
        atoms |= {f"amount:{a}" for a in _amounts(text) if a != "0.00"}
        atoms |= {f"date:{d}" for d in _dates(text)}
        atoms |= {f"email:{e.lower()}" for e in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)}
        atoms |= {f"digits:{d}" for d in re.findall(r"(?<![\d*])\d{4}(?!\d)", text) if not 1900 <= int(d) <= 2100}
        atoms |= {f"phone:{p[-4:]}" for p in re.findall(r"\d[\d\s().-]{8,}\d", text)}
        atoms |= {f"code:{c}" for c in re.findall(r"(?<![\d-])\d{6}(?![\d-])", text)}
        for sentence in re.split(r"[.!?\n]", low):
            words = STATUS_WORDS if CLAIM_REF.search(sentence) else (STRONG_STATUS if strict else ())
            atoms |= {f"status:{w}" for w in words if re.search(rf"\b{w}\b", sentence)}
        remaining = low
        for doc in self._documents:
            if doc in remaining:
                atoms.add(f"document:{doc}")
                remaining = remaining.replace(doc, " ")
        for party, names in self._names.items():
            if any(re.search(rf"\b{re.escape(n)}\b", low) for n in names):
                atoms.add(f"name:{party}")
        grams = _ngrams(low)
        for case_id, phrases in self._phrases.items():
            if any(len(grams & _ngrams(p)) >= 2 for p in phrases):
                atoms.add(f"phrase:{case_id}")
        return atoms

    def _allowed(self, ctx: ResponseContext) -> set[str]:
        text = " ".join(f"{f.value} {f.display}" for f in ctx.facts)
        allowed = self._atoms(text) | {f"date:{k}" for k in _date_keys(text)}
        allowed |= {f"phrase:{cid}" for cid, ps in self._phrases.items() if any(p in text for p in ps)}
        if ctx.masked_email:
            allowed.add(f"email:{ctx.masked_email.lower()}")
        return allowed

    def _other_party(self, atom: str, party: str | None) -> bool:
        kind, _, value = atom.partition(":")
        if kind in ("claim", "phrase"):
            return self._owner.get(value.replace("claim:", ""), party) != party
        if kind == "name":
            return value != party
        if kind in ("digits", "phone", "email"):
            return any(value in vals for pid, vals in self._pii.items() if pid != party)
        return False

    def _scanner_violations(self, reply: str, ctx: ResponseContext) -> list[str]:
        """Second opinion from Presidio: contact details / SSNs never appear unless they are allowlisted facts."""
        if self._scanner is None:
            return []
        allowed = " ".join(f"{f.value} {f.display}" for f in ctx.facts).lower()
        return [f"pii_scan:{entity}" for entity, value in self._scanner.scan(reply)
                if entity in ("PHONE_NUMBER", "EMAIL_ADDRESS", "US_SSN") and value.lower() not in allowed
                and "*" not in value]

    def validate(self, reply: str, cited: list[str], ctx: ResponseContext, caller_text: str) -> ValidationResult:
        violations: list[str] = []
        fact_ids = {f.fact_id for f in ctx.facts}
        violations += [f"unknown_citation:{c}" for c in cited if c not in fact_ids]
        atoms = self._atoms(reply, strict=not ctx.verified)
        if not ctx.verified:
            echo = {a for a in self._atoms(caller_text) if a.startswith(("claim:", "name:"))}
            violations += [f"pre_verification:{a}" for a in sorted(atoms - echo - self._allowed(ctx))]
            if VERIFIED_CLAIM.search(reply):
                violations.append("claims_verified_while_unverified")
        else:
            party = ctx.caller_party_id
            allowed = self._allowed(ctx) | {f"name:{party}"}
            for atom in sorted(atoms - allowed):
                violations.append(("other_party:" if self._other_party(atom, party) else "ungrounded:") + atom)
        violations += self._scanner_violations(reply, ctx)
        if any(f.label == "appeal_deadline_status" and f.value == "passed" for f in ctx.facts) \
                and LIVE_DEADLINE_RE.search(reply):
            violations.append("deadline_presented_as_live")
        for fact_id, pattern in ACTION_CLAIMS.items():
            if pattern.search(reply) and fact_id not in fact_ids:
                violations.append(f"unbacked_action_claim:{fact_id}")
        return ValidationResult(ok=not violations, violations=tuple(violations))
