"""ResponseContext: the ONLY information a responder (LLM or template) may use. Allowlisted per phase."""
from typing import Any

from claims_agent.audit import mask
from claims_agent.controller import ControllerAction, Decision
from claims_agent.domain.models import FrozenModel
from claims_agent.domain.repository import FixtureRepository
from claims_agent.grounding.facts import Fact
from claims_agent.policy.emotion import EmotionStrategy
from claims_agent.state import Phase

SHARED_PREFIXES = ("guideline.", "not_in_data.", "settings.", "schema.", "tool.", "summary.")
OPTION_LABELS = frozenset({"case_id", "case_type", "created_at", "status"})


class ResponseContext(FrozenModel):
    phase: Phase
    action: ControllerAction
    facts: tuple[Fact, ...] = ()
    required_elements: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    details: dict[str, Any] = {}
    emotion: EmotionStrategy
    caller_first_name: str | None = None
    masked_email: str | None = None
    verified: bool = False
    caller_party_id: str | None = None


def _own_option_fact(fact: Fact, party_id: str, repo: FixtureRepository) -> bool:
    if fact.label not in OPTION_LABELS or not fact.fact_id.startswith("claims."):
        return False
    claim = repo.claim(fact.fact_id.split(".")[1])
    return claim is not None and claim.party_id == party_id


def _allowed_facts(decision: Decision, repo: FixtureRepository) -> tuple[Fact, ...]:
    state = decision.state
    if not state.verification.verified:
        return tuple(f for f in decision.facts if f.fact_id.startswith("tool.escalate_to_human"))
    if state.phase == Phase.RESOLVE_INTENT:
        party = state.verification.party_id
        return tuple(f for f in decision.facts
                     if f.fact_id.startswith("tool.") or _own_option_fact(f, party, repo))
    selected = state.selected_case_id
    own = (f"claims.{selected}.", f"derived.{selected}.") if selected else ()
    return tuple(f for f in decision.facts if f.fact_id.startswith(own + SHARED_PREFIXES))


def build_context(decision: Decision, repo: FixtureRepository) -> ResponseContext:
    state = decision.state
    verified = state.verification.verified
    person = repo.policyholder(state.verification.party_id) if verified else None
    return ResponseContext(
        phase=state.phase, action=decision.action, facts=_allowed_facts(decision, repo),
        required_elements=(state.expected_field,) if state.expected_field else (),
        alternatives=decision.alternatives,
        options=tuple(o.display for o in decision.options) if verified else (),
        details=decision.details, emotion=decision.emotion,
        caller_first_name=person.name.split()[0] if person else None,
        masked_email=mask("email", person.email) if person else None, verified=verified,
        caller_party_id=person.party_id if person else None,
    )


def authorized_values(ctx: ResponseContext) -> tuple[str, ...]:
    """Values the caller may hear this turn (used by the eval leak detector and the validator)."""
    values = [f.value for f in ctx.facts]
    return tuple(dict.fromkeys(values))
