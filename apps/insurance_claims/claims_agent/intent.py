"""Case resolution over the VERIFIED caller's own claims only. Pure functions, no I/O."""
import re
from typing import Literal

from claims_agent.domain.models import Claim, FrozenModel
from claims_agent.grounding.facts import month_year
from claims_agent.state import IntentHints

ResolveAction = Literal["PRESENT_CASE", "DISAMBIGUATE_CASE", "NO_MATCHING_CASE", "NO_CLAIMS", "ASK_INTENT"]
ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "last one": -1}


class CaseOption(FrozenModel):
    case_id: str
    case_type: str
    status: str
    month: int
    year: int
    display: str


class Resolution(FrozenModel):
    action: ResolveAction
    case_id: str | None = None
    candidates: tuple[str, ...] = ()
    options: tuple[CaseOption, ...] = ()
    unmatched: tuple[str, ...] = ()


def option_for(claim: Claim) -> CaseOption:
    return CaseOption(case_id=claim.case_id, case_type=claim.case_type, status=claim.status,
                      month=claim.created_at.month, year=claim.created_at.year,
                      display=f"{claim.case_type} claim from {month_year(claim)} ({claim.status})")


FILTERS = (
    ("case_type", lambda c, h: c.case_type == h.case_type),
    ("status", lambda c, h: c.status == h.status),
    ("month", lambda c, h: c.created_at.month == h.month),
    ("year", lambda c, h: c.created_at.year == h.year),
)


def resolve(claims: tuple[Claim, ...], hints: IntentHints) -> Resolution:
    if not claims:
        return Resolution(action="NO_CLAIMS")
    if hints.claim_id:
        match = next((c for c in claims if c.case_id == hints.claim_id), None)
        return Resolution(action="PRESENT_CASE", case_id=match.case_id) if match else Resolution(
            action="NO_MATCHING_CASE", options=tuple(option_for(c) for c in claims))
    if not any((hints.case_type, hints.status, hints.month, hints.year)):
        return Resolution(action="ASK_INTENT", options=tuple(option_for(c) for c in claims))
    pool, unmatched = list(claims), []
    for name, predicate in FILTERS:
        if getattr(hints, name) is None:
            continue
        narrowed = [c for c in pool if predicate(c, hints)]
        if narrowed:
            pool = narrowed
        else:
            unmatched.append(name)
    if len(pool) == 1:
        return Resolution(action="PRESENT_CASE", case_id=pool[0].case_id, unmatched=tuple(unmatched))
    return Resolution(action="DISAMBIGUATE_CASE", candidates=tuple(c.case_id for c in pool),
                      options=tuple(option_for(c) for c in pool), unmatched=tuple(unmatched))


def pick_option(options: tuple[CaseOption, ...], hints: IntentHints, text: str) -> str | None:
    """Match a disambiguation reply to exactly one option, or None."""
    low = text.lower()
    negated = re.search(r"\b(no|nope|nah|not|different|another|other|wrong)\b", low)
    if len(options) == 1 and not negated and re.search(r"\b(yes|yeah|yep|sure|ok(?:ay)?|that one|please|go ahead)\b", low):
        return options[0].case_id
    if hints.claim_id:
        return next((o.case_id for o in options if o.case_id == hints.claim_id), None)
    for word, index in ORDINALS.items():
        if re.search(rf"\b{word}\b", low) and -len(options) <= index < len(options):
            return options[index].case_id
    pool = [o for o in options
            if (hints.status is None or o.status == hints.status)
            and (hints.case_type is None or o.case_type == hints.case_type)
            and (hints.year is None or o.year == hints.year)
            and (hints.month is None or o.month == hints.month)]
    narrowed = any((hints.status, hints.case_type, hints.year, hints.month))
    return pool[0].case_id if narrowed and len(pool) == 1 else None
