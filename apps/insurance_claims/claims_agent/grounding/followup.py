"""Deterministic follow-up guidance from required_document_guideline.json (the grounding source for Q&A)."""
import re
import string

from claims_agent.domain.models import Claim, FrozenModel, Guideline

# claims.json wording -> guideline document key (None = no specific entry; use default guidance).
DOC_ALIASES: dict[str, str | None] = {
    "pathology report": "original pathology report",
    "office note": "treating provider office note",
    "diagnosis report": None,
    "original pathology report": "original pathology report",
    "treating provider office note": "treating provider office note",
    "repair estimate": "repair estimate",
    "accident photos": "supplemental accident scene photos",
    "scene photos": "supplemental accident scene photos",
}
TEMPLATE_KEYS = frozenset({"case_id", "documents", "average_processing_time_after_submission"})
ALTERNATIVES_TOPIC = "missing_required_material_alternatives"


class TemplateKeyError(KeyError):
    """A guideline template referenced a placeholder that is not on the allowlist."""


class Guidance(FrozenModel):
    topic: str
    text: str


def join_documents(docs: tuple[str, ...]) -> str:
    return docs[0] if len(docs) == 1 else ", ".join(docs[:-1]) + f" and {docs[-1]}"


def fill_template(template: str, **values: str) -> str:
    keys = {name for _, name, _, _ in string.Formatter().parse(template) if name}
    unknown = keys - TEMPLATE_KEYS
    if unknown:
        raise TemplateKeyError(f"unexpected template keys: {sorted(unknown)}")
    return template.format(**{k: values[k] for k in keys})


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z']+", text.lower()))


def _score(phrases: tuple[str, ...], text: str) -> int:
    words = _tokens(text)
    low = " ".join(text.lower().split())
    return max((len(p.split()) + (1 if p in low else 0) for p in phrases if _tokens(p) <= words), default=0)


def _render(guideline: Guideline, claim: Claim, template: str) -> str:
    return fill_template(template, case_id=claim.case_id, documents=join_documents(claim.documents_needed),
                         average_processing_time_after_submission=guideline.claim_followup_settings[
                             "average_processing_time_after_submission"]["en"])


def select_followup(guideline: Guideline, claim: Claim, topic: str, text: str, followup_topic: str = "none",
                    document_unavailable: bool = False) -> Guidance | None:
    entries = [e for e in guideline.claim_followup_guidance if not e.requires_documents or claim.documents_needed]
    if document_unavailable:
        alt = next((e for e in entries if e.topic == ALTERNATIVES_TOPIC), None)
        return Guidance(topic=alt.topic, text=_render(guideline, claim, alt.en)) if alt else None
    if topic != "none":
        entries = [e for e in entries if topic in e.intent_hints] or entries
    scored = [(_score(e.match_any, text), e.topic == followup_topic, -i, e) for i, e in enumerate(entries)]
    scored = [s for s in scored if s[0] > 0 or s[1]]
    if not scored:
        return None
    best = max(scored, key=lambda s: s[:3])[3]
    return Guidance(topic=best.topic, text=_render(guideline, claim, best.en))


def fallback_guidance(guideline: Guideline, claim: Claim) -> Guidance | None:
    if not claim.documents_needed:
        return None
    return Guidance(topic="fallback", text=guideline.claim_followup_fallback["en"])


def document_guidance(guideline: Guideline, claim: Claim, document: str, unavailable: bool) -> Guidance:
    key = DOC_ALIASES.get(document.lower())
    if unavailable:
        source = guideline.document_alternative_guidance.get(key or "", guideline.document_alternative_guidance["default"])
        return Guidance(topic=f"document_alternative:{key or 'default'}", text=source["en"])
    if key and key in guideline.document_guidance:
        return Guidance(topic=f"document:{key}", text=guideline.document_guidance[key]["en"])
    parts = [guideline.default_guidance["en"]]
    if case_specific := guideline.case_type_guidance.get(claim.case_type):
        parts.append(case_specific["en"])
    return Guidance(topic="document:default", text=" ".join(parts))
