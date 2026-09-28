"""Mock one-time-passcode service (possession factor). Codes go ONLY to the matched record's on-file contact.

`issue` is called whether or not a record matched: with no match nothing is delivered, and every later code
fails - so the caller-facing flow is identical either way (no existence oracle).
"""
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator, Literal

log = logging.getLogger(__name__)
OtpStatus = Literal["ok", "wrong", "expired", "exhausted", "none"]


@dataclass(frozen=True)
class OtpDelivery:
    to: str
    code: str


@dataclass
class _Record:
    party_id: str | None
    code: str | None
    expires_at: float
    attempts: int = 0


@dataclass
class MockOtpService:
    ttl_seconds: int = 300
    max_attempts: int = 3
    codes: Iterator[str] | None = None
    reveal_in_log: bool = False
    clock: Callable[[], float] = time.monotonic
    outbox: list[OtpDelivery] = field(default_factory=list)
    _records: dict[str, _Record] = field(default_factory=dict)
    _offset: float = 0.0

    def _now(self) -> float:
        return self.clock() + self._offset

    def advance(self, seconds: float) -> None:  # test/demo helper
        self._offset += seconds

    def _new_code(self) -> str:
        return next(self.codes) if self.codes else f"{secrets.randbelow(10**6):06d}"

    def issue(self, session_id: str, party_id: str | None, contact: str | None) -> None:
        code = self._new_code() if party_id and contact else None
        self._records[session_id] = _Record(party_id if code else None, code, self._now() + self.ttl_seconds)
        if code:
            self.outbox.append(OtpDelivery(to=contact, code=code))
            if self.reveal_in_log:
                log.info("MOCK OTP delivered to on-file contact: %s", code)

    def check(self, session_id: str, code: str) -> tuple[OtpStatus, str | None]:
        record = self._records.get(session_id)
        if record is None:
            return "none", None
        if self._now() > record.expires_at:
            self._records.pop(session_id, None)
            return "expired", record.party_id  # internal: lets the controller count the failure per record
        record.attempts += 1
        if record.code is not None and secrets.compare_digest(code, record.code):
            self._records.pop(session_id, None)
            return "ok", record.party_id
        if record.attempts >= self.max_attempts:
            self._records.pop(session_id, None)
            return "exhausted", record.party_id
        return "wrong", None
