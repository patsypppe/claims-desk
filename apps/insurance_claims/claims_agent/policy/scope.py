"""Stateful scope control: redirect isolated off-topic turns, escalate repeated ones."""
import re
from typing import Literal

from claims_agent.domain.models import FrozenModel
from claims_agent.extraction.schema import TurnAnalysis
from claims_agent.state import ConversationState

UNSAFE_RE = re.compile(r"(system prompt|developer mode|dev mode|jailbreak|your instructions|"
                       r"(all|every|other) (customers?|people|members?)'?s?\b|someone else'?s|"
                       r"list all (claims|customers|policies))", re.I)


OTHER_PERSON_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+'s\s+(?i:claims?|account|policy|information|details)")


class ScopeDecision(FrozenModel):
    kind: Literal["redirect", "refuse_unsafe", "escalate"]
    count: int
    offer_human: bool


def decide_scope(analysis: TurnAnalysis, text: str, state: ConversationState, offer_threshold: int,
                 escalation_threshold: int) -> ScopeDecision | None:
    unsafe = bool(UNSAFE_RE.search(text) or OTHER_PERSON_RE.search(text))
    off_topic = analysis.scope == "OUT_OF_SCOPE" and not analysis.pii_candidates
    if not (unsafe or off_topic):
        return None
    count = state.counters.out_of_scope + 1
    if count >= escalation_threshold:
        return ScopeDecision(kind="escalate", count=count, offer_human=True)
    kind = "refuse_unsafe" if unsafe else "redirect"
    return ScopeDecision(kind=kind, count=count, offer_human=count >= offer_threshold)
