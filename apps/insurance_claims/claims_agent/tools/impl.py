"""Tool implementations. Identity scope always comes from state, never from arguments."""
from claims_agent.audit import mask
from claims_agent.grounding.facts import Fact, claim_detail_facts, claim_option_facts, derived_facts
from claims_agent.grounding.summary import build_summary as assemble_summary
from claims_agent.grounding.followup import document_guidance, fallback_guidance, select_followup
from claims_agent.state import PII_FIELDS, ConversationState
from claims_agent.representatives import listed_representative
from claims_agent.tools.mocks import EmailSendError
from claims_agent.tools.registry import (
    ToolFailure,
    ToolResult,
    ToolSpec,
    require_email_consent,
    require_not_escalated,
    require_selected_case,
    require_third_party,
    require_unverified,
    require_verified,
)


def verify_identity(reg, state: ConversationState) -> ToolResult:
    outcome = reg.verifier.evaluate(state)
    return ToolResult(ok=outcome.status == "verified", data=outcome.model_dump())


def search_claims(reg, state: ConversationState) -> ToolResult:
    claims = reg.repo.claims_for(state.verification.party_id)
    facts = tuple(f for c in claims for f in claim_option_facts(c))
    return ToolResult(ok=True, facts=facts, data={"case_ids": [c.case_id for c in claims]})


def get_claim_details(reg, state: ConversationState, case_id: str | None = None) -> ToolResult:
    claim = reg.repo.claim(case_id or state.selected_case_id or "")
    # Other parties' claims and non-existent claims are indistinguishable to the caller.
    if claim is None or claim.party_id != state.verification.party_id:
        return ToolResult(ok=False, error="not_on_account")
    facts = claim_detail_facts(claim) + derived_facts(claim, reg.clock.today())
    return ToolResult(ok=True, facts=facts, data={"case_id": claim.case_id})


def _guidance_fact(case_id: str, kind: str, guidance) -> Fact:
    return Fact(fact_id=f"guideline.{kind}.{guidance.topic}@{case_id}", label="answer", value=guidance.text,
                display=guidance.text)


def get_followup_guidance(reg, state: ConversationState, topic: str = "none", text: str = "",
                          followup_topic: str = "none", document_unavailable: bool = False) -> ToolResult:
    claim = reg.repo.claim(state.selected_case_id)
    guidance = select_followup(reg.repo.guideline, claim, topic, text, followup_topic, document_unavailable)
    guidance = guidance or fallback_guidance(reg.repo.guideline, claim)
    if guidance is None:
        return ToolResult(ok=False, error="no_guidance")
    return ToolResult(ok=True, facts=(_guidance_fact(claim.case_id, "followup", guidance),),
                      data={"topic": guidance.topic})


def get_document_guidance(reg, state: ConversationState, document: str = "", unavailable: bool = False) -> ToolResult:
    claim = reg.repo.claim(state.selected_case_id)
    guidance = document_guidance(reg.repo.guideline, claim, document, unavailable)
    return ToolResult(ok=True, facts=(_guidance_fact(claim.case_id, "document", guidance),),
                      data={"topic": guidance.topic})


def send_summary_email(reg, state: ConversationState, subject: str = "", body: str = "") -> ToolResult:
    person = reg.repo.policyholder(state.verification.party_id)
    try:
        message_id = reg.email_sender.send(to=person.email, subject=subject, body=body)
    except EmailSendError as exc:
        raise ToolFailure("send_failed") from exc
    masked = mask("email", person.email)
    fact = Fact(fact_id="tool.send_summary_email.result", label="email_sent", value="sent",
                display=f"summary emailed to {masked}")
    return ToolResult(ok=True, facts=(fact,), data={"message_id": message_id, "masked_to": masked})


def _verification_summary(state: ConversationState) -> dict:
    """What a human agent needs to NOT re-verify: method, masked factors, representative authority."""
    v = state.verification
    rep = None
    if v.method == "representative":
        rep = {"name": state.speaker.rep_name, "relationship": state.speaker.relationship,
               "policyholder_consent": "approved"}
    return {"method": v.method if v.verified else None,
            "factors": {f: o.masked for f in PII_FIELDS if (o := state.current(f))},
            "representative": rep}


def escalate_to_human(reg, state: ConversationState, reason: str = "unspecified") -> ToolResult:
    verified = state.verification.verified
    summary = assemble_summary(reg.repo, state, reg.clock.today()).body if verified else None
    payload = {
        "reason": reason,
        "phase": state.phase.value,
        "party_id": state.verification.party_id if verified else None,
        "selected_case_id": state.selected_case_id if verified else None,
        "captured_fields": {f: o.masked for f in PII_FIELDS if (o := state.current(f))},
        "verification": _verification_summary(state),
        "case_summary": summary,
        "topic": state.intent.topic,
        "counters": state.counters.model_dump(),
    }
    ticket_id = reg.handoff.create(payload)
    fact = Fact(fact_id="tool.escalate_to_human.ticket", label="ticket_id", value=ticket_id,
                display=ticket_id)
    return ToolResult(ok=True, facts=(fact,), data={"ticket_id": ticket_id, "reason": reason})


def request_representative_consent(reg, state: ConversationState) -> ToolResult:
    """Verify the policyholder's factors, confirm the caller is their listed representative, then ask the
    policyholder out-of-band (mock poll). Only 'approved' grants access; anything else fails closed."""
    outcome = reg.verifier.evaluate(state)
    if outcome.status != "verified":
        return ToolResult(ok=False, data={"verification": outcome.status,
                                          "candidate_party_id": outcome.candidate_party_id})
    if listed_representative(reg.repo, state.speaker, outcome.party_id) is None:
        return ToolResult(ok=False, data={"verification": "failed", "candidate_party_id": outcome.party_id})
    status = reg.consent_service.request_and_poll(outcome.party_id)
    return ToolResult(ok=status == "approved", data={"status": status, "party_id": outcome.party_id})


def build_summary(reg, state: ConversationState) -> ToolResult:
    summary = assemble_summary(reg.repo, state, reg.clock.today())
    fact = Fact(fact_id="summary.body", label="summary", value=summary.body, display=summary.body)
    return ToolResult(ok=True, facts=(fact,), data={"subject": summary.subject, "body": summary.body})


def send_otp(reg, state: ConversationState, suppress_delivery: bool = False) -> ToolResult:
    """Route a code to the on-file email of the record matching every supplied factor (if any).

    The result is identical whether or not a record matched (or delivery was suppressed for a locked record).
    """
    party = None if suppress_delivery else reg.verifier.partial_match(state)
    person = reg.repo.policyholder(party) if party else None
    reg.otp.issue(state.session_id, party, person.email if person else None)
    return ToolResult(ok=True, data={"issued": True})


def verify_otp(reg, state: ConversationState, code: str = "") -> ToolResult:
    status, party = reg.otp.check(state.session_id, code)
    ok = status == "ok"
    return ToolResult(ok=ok, data={"status": status, "party_id": party if ok else None, "candidate": party})


def accept_channel_assertion(reg, state: ConversationState, token: str = "") -> ToolResult:
    party = reg.channel.verify(token) if reg.channel and token else None
    valid = party is not None and reg.repo.policyholder(party) is not None
    return ToolResult(ok=valid, data={"party_id": party if valid else None})


def default_specs() -> list[ToolSpec]:
    return [
        ToolSpec("verify_identity", verify_identity),
        ToolSpec("send_otp", send_otp, require_unverified),
        ToolSpec("accept_channel_assertion", accept_channel_assertion, require_unverified),
        ToolSpec("verify_otp", verify_otp, require_unverified),
        ToolSpec("request_representative_consent", request_representative_consent, require_third_party),
        ToolSpec("search_claims", search_claims, require_verified),
        ToolSpec("get_claim_details", get_claim_details, require_selected_case),
        ToolSpec("get_followup_guidance", get_followup_guidance, require_selected_case),
        ToolSpec("get_document_guidance", get_document_guidance, require_selected_case),
        ToolSpec("build_summary", build_summary, require_verified),
        ToolSpec("send_summary_email", send_summary_email, require_email_consent),
        ToolSpec("escalate_to_human", escalate_to_human, require_not_escalated),
    ]
