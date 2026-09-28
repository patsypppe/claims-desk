"""Identity verification outcome (IdentityVerifier is added in Task 5)."""
from typing import Literal

from claims_agent.domain.models import FrozenModel


class VerifyOutcome(FrozenModel):
    status: Literal["verified", "insufficient", "failed"]
    party_id: str | None = None
    internal_reason: str
