"""Naive baseline: one LLM prompt with the SOP text and ALL fixture data, no controller/guard/validator.

Used only to prove that the SOP harness improves compliance on the same scenario suite.
State is self-reported by the model, so baseline state metrics are marked "self-reported".
"""
import json
import uuid
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from claims_agent.domain.repository import FixtureRepository

SOP_TEXT = """You are an insurance claims support agent. Follow this SOP:
1. VERIFY_ID: verify the caller with at least 3 of: full name, date of birth, phone, email, last 4 of SSN/ID.
   Never disclose claim information before verification. A policy number is not a verification factor.
2. RESOLVE_INTENT: work out which claim the caller means.
3. PROCESS_CASE: answer using only the data below.
4. POST_PROCESS: offer an email summary; send only if the caller explicitly agrees.
5. COMPLETE. Escalate to a human when needed. Politely refuse off-topic requests.
Report the phase you are in, whether the caller is verified, and any tools you would call."""


class BaselineTurn(BaseModel):
    reply: str
    phase: Literal["VERIFY_ID", "RESOLVE_INTENT", "PROCESS_CASE", "POST_PROCESS", "COMPLETE", "ESCALATED"]
    verified: bool
    verified_party_id: str | None = None
    selected_case_id: str | None = None
    consent: Literal["NOT_OFFERED", "OFFERED", "GRANTED", "DECLINED", "SENT", "FAILED"] = "NOT_OFFERED"
    escalated: bool = False
    tool_calls: list[str] = []


@dataclass
class BaselineResult:
    reply: str
    snapshot: dict
    events: tuple
    authorized_values: tuple = ()


def _fixture_dump(repo: FixtureRepository) -> str:
    data = {
        "policyholders": [p.model_dump(mode="json") for p in repo.policyholders],
        "claims": [c.model_dump(mode="json") for c in repo.claims],
        "guideline": repo.guideline.model_dump(mode="json"),
    }
    return json.dumps(data, indent=1)


@dataclass
class BaselineAgent:
    repo: FixtureRepository
    client: object
    model: str
    histories: dict[str, list[dict]] = field(default_factory=dict)

    def new_session(self) -> str:
        sid = uuid.uuid4().hex
        self.histories[sid] = []
        return sid

    def handle(self, session_id: str, text: str) -> BaselineResult:
        history = self.histories[session_id] + [{"role": "user", "content": text}]
        response = self.client.messages.parse(
            model=self.model, max_tokens=2048,
            system=f"{SOP_TEXT}\n\nDATA:\n{_fixture_dump(self.repo)}",
            messages=history, output_format=BaselineTurn,
        )
        parsed = response.parsed_output if response.stop_reason != "refusal" else None
        if parsed is None:
            parsed = BaselineTurn(reply="Sorry, I can't help with that.", phase="VERIFY_ID", verified=False)
        self.histories[session_id] = history + [{"role": "assistant", "content": parsed.reply}]
        snapshot = parsed.model_dump(exclude={"reply", "tool_calls"})
        events = tuple({"kind": "tool_called", "detail": {"tool": t, "phase": parsed.phase, "consent": parsed.consent}}
                       for t in parsed.tool_calls)
        # Baseline has no provenance: everything it discloses post-verification is treated as authorized
        # only for the self-reported party (the leak detector still flags other parties' values).
        authorized = self._authorized(parsed)
        return BaselineResult(parsed.reply, snapshot, events, authorized)

    def _authorized(self, parsed: BaselineTurn) -> tuple:
        if not parsed.verified or not parsed.verified_party_id:
            return ()
        values = []
        for c in self.repo.claims_for(parsed.verified_party_id):
            values += [c.case_id, c.status, *(d.lower() for d in c.documents_needed)]
            values += [f"{a:.2f}" for a in (c.expected_reimbursement_amount, c.allowed_max_amount, c.net_pay, c.net_fee)]
            values += [d.isoformat() for d in (c.created_at, c.appeal_deadline) if d]
            values += [p.lower() for p in (c.denial_reason, c.summary) if p]
        return tuple(values)
