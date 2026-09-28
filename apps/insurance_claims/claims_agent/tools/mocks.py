"""Mock external systems: email, human handoff and out-of-band policyholder consent."""
from dataclasses import dataclass, field


class EmailSendError(RuntimeError):
    """Raised by the email sender when delivery fails."""


@dataclass(frozen=True)
class SentEmail:
    to: str
    subject: str
    body: str
    message_id: str


@dataclass
class MockEmailSender:
    fail: bool = False
    outbox: list[SentEmail] = field(default_factory=list)

    def send(self, *, to: str, subject: str, body: str) -> str:
        if self.fail:
            raise EmailSendError("mock email provider unavailable")
        message_id = f"MSG-{len(self.outbox) + 1:04d}"
        self.outbox.append(SentEmail(to=to, subject=subject, body=body, message_id=message_id))
        return message_id


@dataclass
class MockHandoff:
    tickets: list[dict] = field(default_factory=list)

    def create(self, payload: dict) -> str:
        ticket_id = f"HND-{len(self.tickets) + 1:04d}"
        self.tickets.append({**payload, "ticket_id": ticket_id})
        return ticket_id


@dataclass
class MockConsentService:
    """Replays a consent_scenarios.json status sequence; one element per poll."""
    sequence: tuple[str, ...]
    requests: list[str] = field(default_factory=list)

    def request_and_poll(self, party_id: str) -> str:
        self.requests.append(party_id)
        for status in self.sequence:
            if status in ("approved", "denied"):
                return status
        return "timeout"
