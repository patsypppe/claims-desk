"""Identity verification: ≥3 approved factors that ALL match ONE record.

The caller-facing failure message is identical for every failure reason so the agent cannot be
used as an oracle for which field was wrong or whether a record exists.
"""
from typing import Literal

from claims_agent.domain.models import FrozenModel, Policyholder
from claims_agent.domain.repository import FixtureRepository
from claims_agent.normalize import name_tokens
from claims_agent.state import ConversationState

MIN_FACTORS = 3
KNOWLEDGE_FACTORS = frozenset({"dob", "id_last4"})
GENERIC_FAILURE = ("I wasn't able to verify your identity with those details. You can re-confirm them or share "
                   "another item: your date of birth, phone number, email address, or the last four digits of "
                   "your SSN or national ID.")


class VerifyOutcome(FrozenModel):
    status: Literal["verified", "insufficient", "failed"]
    party_id: str | None = None
    internal_reason: str
    candidate_party_id: str | None = None  # internal only (lockout accounting); never shown to the caller


def factor_matches(person: Policyholder, field: str, value: str) -> bool:
    if field == "name":
        return name_tokens(value) in {name_tokens(n) for n in (person.name, *person.name_aliases)}
    if field == "dob":
        return value == person.dob.isoformat()
    if field == "phone":
        return value in {person.phone, *person.phone_aliases}
    if field == "email":
        return value in {e.lower() for e in (person.email, *person.email_aliases)}
    if field == "id_last4":
        return value == person.id_last4
    return False


class IdentityVerifier:
    def __init__(self, repo: FixtureRepository, require_knowledge_factor: bool = False) -> None:
        self._repo = repo
        self._require_knowledge = require_knowledge_factor

    @staticmethod
    def failure_message(_internal_reason: str) -> str:
        return GENERIC_FAILURE

    def _enough(self, factors: dict[str, str]) -> bool:
        if len(factors) < MIN_FACTORS:
            return False
        return not self._require_knowledge or bool(KNOWLEDGE_FACTORS & factors.keys())

    def evaluate(self, state: ConversationState) -> VerifyOutcome:
        factors = state.current_values()
        if not self._enough(factors):
            return VerifyOutcome(status="insufficient", internal_reason="insufficient")
        policy = state.lookup.policy_number
        scored = [(sum(factor_matches(p, f, v) for f, v in factors.items()), p) for p in self._repo.policyholders]
        best_score, best = max(scored, key=lambda item: item[0])
        if best_score == len(factors):
            if policy and policy != best.policy_number:
                return VerifyOutcome(status="failed", internal_reason="policy_mismatch",
                                     candidate_party_id=best.party_id)
            return VerifyOutcome(status="verified", party_id=best.party_id, internal_reason="ok")
        reason = "no_match" if best_score == 0 else "conflict"
        return VerifyOutcome(status="failed", internal_reason=reason,
                             candidate_party_id=best.party_id if best_score else None)
