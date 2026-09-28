"""Redact high-sensitivity values before any text reaches an LLM provider; restore them deterministically.

The extractor sees placeholders like ⟦DOB_1⟧. It may return a placeholder as a raw_value; only placeholders issued
for THIS turn map back to real values (invented ones are dropped). Names stay visible: they are needed for
understanding and are the least sensitive of the approved factors.
"""
import re
from datetime import date

from claims_agent.audit import AuditEvent
from claims_agent.domain.models import FrozenModel
from claims_agent.extraction import lexicon as lx
from claims_agent.extraction.schema import TurnAnalysis

PLACEHOLDER_RE = re.compile(r"⟦[A-Z0-9]+_\d+⟧")


class Redaction(FrozenModel):
    text: str
    mapping: dict[str, str]


SSN_RE = re.compile(r"(?<!\d)\d{3}[- ]\d{2}[- ]\d{4}(?!\d)")
SPELLED_DATE_RE = re.compile(r"\b(?:the\s+)?[a-z]+(?:st|nd|rd|th)?\s+(?:day\s+)?of\s+" + lx.MONTH_ALT
                             + r",?\s+\d{4}", re.I)


def _spans(text: str, today: date) -> list[tuple[int, int, str]]:
    spans = [(m.start(), m.end(), "EMAIL") for m in lx.EMAIL_RE.finditer(text)]
    spans += [(m.start(), m.end(), "SSN") for m in SSN_RE.finditer(text)]
    spans += [(m.start(), m.end(), "PHONE") for m in lx.PHONE_RE.finditer(text)]
    for pattern in (*lx.DATE_RES, SPELLED_DATE_RE):  # any date-like span, valid or not (fail-safe)
        spans += [(m.start(), m.end(), "DOB") for m in pattern.finditer(text)]
    spans += [(m.start(), m.end(), "CODE") for m in re.finditer(r"(?<!\d)\d{6}(?!\d)", text)]
    for m in lx.FOUR_DIGITS_RE.finditer(text):
        cue = lx.ID_WORD_RE.search(text[max(0, m.start() - 30):m.start()])
        if cue or not 1900 <= int(m.group(0)) <= 2100:  # after an ID cue, any value (even "1987") is an ID
            spans.append((m.start(), m.end(), "ID4"))
    chosen: list[tuple[int, int, str]] = []
    for span in sorted(spans, key=lambda s: (s[0], -(s[1] - s[0]))):
        if not chosen or span[0] >= chosen[-1][1]:
            chosen.append(span)
    return chosen


def redact(text: str, today: date) -> Redaction:
    mapping: dict[str, str] = {}
    counters: dict[str, int] = {}
    out, cursor = [], 0
    for start, end, kind in _spans(text, today):
        counters[kind] = counters.get(kind, 0) + 1
        placeholder = f"⟦{kind}_{counters[kind]}⟧"
        mapping[placeholder] = text[start:end]
        out += [text[cursor:start], placeholder]
        cursor = end
    out.append(text[cursor:])
    return Redaction(text="".join(out), mapping=mapping)


def _restore_value(value: str | None, mapping: dict[str, str]) -> tuple[str | None, bool]:
    if not value:
        return value, True
    placeholders = PLACEHOLDER_RE.findall(value)
    if any(p not in mapping for p in placeholders):
        return None, False
    for p in placeholders:
        value = value.replace(p, mapping[p])
    return value, True


def restore_analysis(analysis: TurnAnalysis, mapping: dict[str, str], turn: int) -> tuple[TurnAnalysis, list]:
    events, kept = [], []
    for cand in analysis.pii_candidates:
        value, ok = _restore_value(cand.raw_value, mapping)
        if ok:
            kept.append(cand.model_copy(update={"raw_value": value or ""}))
        else:
            events.append(AuditEvent(kind="llm_value_rejected", turn=turn,
                                     detail={"field": cand.field, "reason": "unknown_placeholder"}))
    policy, _ = _restore_value(analysis.policy_number, mapping)
    claim, _ = _restore_value(analysis.intent.claim_id, mapping)
    return analysis.model_copy(update={"pii_candidates": kept, "policy_number": policy,
                                       "intent": analysis.intent.model_copy(update={"claim_id": claim})}), events
