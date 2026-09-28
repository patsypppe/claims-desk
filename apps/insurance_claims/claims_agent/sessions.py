"""Server-side sessions (ids are server-issued only) and cross-session verification lockouts."""
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from claims_agent.domain.repository import FixtureRepository
from claims_agent.state import ConversationState
from claims_agent.verification import factor_matches


class UnknownSessionError(KeyError):
    """Raised for session ids this server never issued (or that expired)."""


@dataclass
class LockoutRegistry:
    """Counts failed verifications per candidate record across sessions (survives conversation reset)."""
    failures: dict[str, int] = field(default_factory=dict)

    def record_failure(self, party_id: str) -> None:
        self.failures[party_id] = self.failures.get(party_id, 0) + 1

    def is_locked(self, state: ConversationState, repo: FixtureRepository, threshold: int) -> bool:
        factors = state.current_values()
        if not factors:
            return False
        for person in repo.policyholders:
            if self.failures.get(person.party_id, 0) < threshold:
                continue
            if any(factor_matches(person, f, v) for f, v in factors.items()):
                return True
        return False


@dataclass
class SessionStore:
    ttl_seconds: int = 1800
    now: Callable[[], float] = time.monotonic
    _states: dict[str, tuple[ConversationState, float]] = field(default_factory=dict)

    def create(self) -> str:
        sid = uuid.uuid4().hex
        self._states[sid] = (ConversationState(session_id=sid), self.now())
        return sid

    def get(self, sid: str) -> ConversationState:
        entry = self._states.get(sid)
        if entry is None:
            raise UnknownSessionError(sid)
        state, last_seen = entry
        if self.now() - last_seen > self.ttl_seconds:
            del self._states[sid]
            raise UnknownSessionError(sid)
        return state

    def save(self, state: ConversationState) -> None:
        self._states[state.session_id] = (state, self.now())

    def drop(self, sid: str) -> None:
        self._states.pop(sid, None)
