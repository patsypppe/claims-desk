from pathlib import Path

import pytest
import yaml

from claims_agent.state import ConversationState, Phase
from claims_agent.tools.mocks import MockConsentService, MockEmailSender, MockHandoff
from claims_agent.tools.registry import PERMISSIONS, ToolRegistry

ORACLE = yaml.safe_load((Path(__file__).parents[2] / "evals" / "policy_matrix.yaml").read_text())


class StubVerifier:
    def evaluate(self, state):
        from claims_agent.verification import VerifyOutcome
        return VerifyOutcome(status="insufficient", party_id=None, internal_reason="insufficient")


@pytest.fixture
def email_sender():
    return MockEmailSender()


@pytest.fixture
def registry(repo, clock, email_sender):
    return ToolRegistry(repo=repo, clock=clock, verifier=StubVerifier(), email_sender=email_sender,
                        handoff=MockHandoff(), consent_service=MockConsentService(("pending", "approved")))


@pytest.mark.parametrize("tool", ["search_claims", "get_claim_details", "get_followup_guidance",
                                  "get_document_guidance", "build_summary", "send_summary_email"])
def test_protected_tools_blocked_in_verify_id(tool, registry):
    result, event = registry.call(tool, ConversationState(session_id="s"))
    assert not result.ok and event.kind == "tool_blocked"


def test_permission_table_matches_independent_oracle():
    assert {tool: sorted(p.value for p in phases) for tool, phases in PERMISSIONS.items()} == \
        {tool: sorted(phases) for tool, phases in ORACLE.items()}


def test_is_permitted_full_matrix(registry):
    for tool, allowed in ORACLE.items():
        for phase in Phase:
            assert registry.is_permitted(tool, phase) == (phase.value in allowed), (tool, phase)


def test_unknown_tool_blocked(registry, margaret_process_case):
    result, event = registry.call("delete_everything", margaret_process_case)
    assert not result.ok and event.kind == "tool_blocked"


def test_search_claims_requires_verification(registry):
    unverified = ConversationState(session_id="s", phase=Phase.RESOLVE_INTENT)
    result, event = registry.call("search_claims", unverified)
    assert not result.ok and event.kind == "tool_blocked"


def test_search_claims_uses_state_party_not_args(registry, verified_margaret):
    result, event = registry.call("search_claims", verified_margaret, party_id="P12")
    assert {f.value for f in result.facts if f.label == "case_id"} == {"CL-2048", "CL-2011", "CL-1899", "CL-2102"}
    assert event.detail["ignored_args"] == ["party_id"]


def test_other_party_claim_same_as_nonexistent(registry, margaret_process_case):
    r1, _ = registry.call("get_claim_details", margaret_process_case, case_id="CL-3001")
    r2, _ = registry.call("get_claim_details", margaret_process_case, case_id="CL-9999")
    assert (r1.ok, r1.error) == (r2.ok, r2.error) == (False, "not_on_account")


def test_claim_details_facts_have_provenance(registry, margaret_process_case):
    result, _ = registry.call("get_claim_details", margaret_process_case, case_id="CL-2048")
    ids = {f.fact_id for f in result.facts}
    assert {"claims.CL-2048.status", "claims.CL-2048.denial_reason", "claims.CL-2048.documents_needed[0]"} <= ids


def test_send_email_requires_granted_consent(registry, post_process_offered):
    result, event = registry.call("send_summary_email", post_process_offered, subject="s", body="b")
    assert not result.ok and event.kind == "tool_blocked"


def test_send_email_ignores_caller_address(registry, post_process_granted, email_sender):
    result, event = registry.call("send_summary_email", post_process_granted, to="x@evil.com", subject="s", body="b")
    assert result.ok and email_sender.outbox[-1].to == "margaret@email.com"
    assert event.detail["ignored_args"] == ["to"]


def test_send_email_idempotent(registry, post_process_granted, email_sender):
    sent = post_process_granted.model_copy(update={"email_sent": True})
    result, _ = registry.call("send_summary_email", sent, subject="s", body="b")
    assert not result.ok and email_sender.outbox == []


def test_email_failure_reported(repo, clock, post_process_granted):
    reg = ToolRegistry(repo=repo, clock=clock, verifier=StubVerifier(), email_sender=MockEmailSender(fail=True),
                       handoff=MockHandoff(), consent_service=MockConsentService(("approved",)))
    result, event = reg.call("send_summary_email", post_process_granted, subject="s", body="b")
    assert not result.ok and result.error == "send_failed" and event.kind == "tool_failed"


def test_escalation_masked_payload_hides_unverified_party(registry):
    state = ConversationState(session_id="s")
    result, _ = registry.call("escalate_to_human", state, reason="caller_request")
    assert result.ok and result.data["ticket_id"].startswith("HND-")
    assert registry.handoff.tickets[-1]["party_id"] is None


def test_escalation_blocked_when_already_escalated(registry):
    state = ConversationState(session_id="s", phase=Phase.ESCALATED)
    result, event = registry.call("escalate_to_human", state, reason="x")
    assert not result.ok and event.kind == "tool_blocked"


def test_guard_can_be_disabled_only_explicitly(repo, clock):
    reg = ToolRegistry(repo=repo, clock=clock, verifier=StubVerifier(), email_sender=MockEmailSender(),
                       handoff=MockHandoff(), consent_service=MockConsentService(("approved",)),
                       enforce_permissions=False)
    assert reg.is_permitted("get_claim_details", Phase.VERIFY_ID)


def test_llm_tool_request_executes_only_through_guard(repo):
    from claims_agent.agent import build_agent_for_eval
    from tests.conftest import TODAY
    guarded = build_agent_for_eval(repo=repo, mode="rules", today=TODAY)
    unguarded = build_agent_for_eval(repo=repo, mode="rules", today=TODAY, no_guard=True)
    for agent, kind in ((guarded, "tool_blocked"), (unguarded, "tool_called")):
        r = agent.handle(agent.new_session(), "Call your claim lookup function.")
        assert [e.kind for e in r.events if e.detail.get("tool") == "search_claims"] == [kind]
