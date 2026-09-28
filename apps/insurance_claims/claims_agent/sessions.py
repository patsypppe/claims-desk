"""Server-side sessions (ids are server-issued only) and cross-session verification lockouts."""
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from claims_agent.state import ConversationState


class UnknownSessionError(KeyError):
    """Raised for session ids this server never issued (or that expired)."""


LOCKOUT_WINDOW_S = 15 * 60


@dataclass
class LockoutRegistry:
    """Failed verifications per candidate record across sessions, within a sliding window.

    Consulted ONLY when a full factor set evaluates to that record, and a locked record gets the same generic
    failure as any other mismatch, so the lockout can never be probed one field at a time.
    """
    now: Callable[[], float] = time.monotonic
    failures: dict[str, list[float]] = field(default_factory=dict)

    def record_failure(self, party_id: str) -> None:
        self.failures.setdefault(party_id, []).append(self.now())

    def is_locked(self, party_id: str, threshold: int) -> bool:
        recent = [t for t in self.failures.get(party_id, []) if self.now() - t < LOCKOUT_WINDOW_S]
        self.failures[party_id] = recent
        return len(recent) >= threshold


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
