import pytest

from claims_agent.agent import build_agent_for_eval
from claims_agent.extraction.schema import PiiCandidate, TurnAnalysis
from claims_agent.privacy.redact import redact, restore_analysis
from tests.conftest import TODAY

SAMPLE = ("I'm Margaret Chen, DOB 1985-03-15, SSN last four 4472, phone (650) 521-2836, "
          "email margaret@email.com, about my denied healthcare claim from January.")


def test_redaction_removes_sensitive_values_and_keeps_context():
    r = redact(SAMPLE, TODAY)
    for raw in ("1985-03-15", "4472", "521-2836", "margaret@email.com"):
        assert raw not in r.text
    assert "healthcare claim from January" in r.text and "Margaret Chen" in r.text
    assert set(r.mapping.values()) >= {"1985-03-15", "4472", "margaret@email.com"}


def test_placeholders_round_trip_and_invented_ones_are_dropped():
    r = redact(SAMPLE, TODAY)
    dob_ph = next(k for k, v in r.mapping.items() if v == "1985-03-15")
    llm = TurnAnalysis(pii_candidates=[PiiCandidate(field="dob", raw_value=dob_ph),
                                       PiiCandidate(field="id_last4", raw_value="⟦ID4_9⟧")])
    restored, events = restore_analysis(llm, r.mapping, turn=1)
    assert [(c.field, c.raw_value) for c in restored.pii_candidates] == [("dob", "1985-03-15")]
    assert events and events[0].kind == "llm_value_rejected"


def test_llm_prompt_never_sees_raw_dob_or_id(repo):
    agent = build_agent_for_eval(repo=repo, mode="fake", today=TODAY, scripted_analyses=[{}])
    agent.handle(agent.new_session(), SAMPLE)
    prompt = agent.extraction_llm.calls[0]["user"]
    assert "1985-03-15" not in prompt and "4472" not in prompt and "margaret@email.com" not in prompt
    assert "⟦" in prompt


def test_sensitive_turn_makes_no_llm_call(repo):
    agent = build_agent_for_eval(repo=repo, mode="fake", today=TODAY, scripted_analyses=[{}])
    r = agent.handle(agent.new_session(), "4472", sensitive=True)
    assert agent.extraction_llm.calls == [] and r.snapshot.phase == "VERIFY_ID"


def test_presidio_scanner_flags_phone_and_email():
    from claims_agent.privacy.presidio_scan import PresidioScanner
    scanner = PresidioScanner.try_create()
    if scanner is None:
        pytest.skip("presidio/spaCy model not installed")
    found = {e for e, _ in scanner.scan("Call me at 650-521-2836 or write to someone@example.com about CL-2048")}
    assert {"PHONE_NUMBER", "EMAIL_ADDRESS", "CLAIM_ID"} <= found


def test_validator_uses_presidio_for_unauthorized_contact_details(repo):
    from claims_agent.controller import ControllerAction, Decision
    from claims_agent.privacy.presidio_scan import PresidioScanner
    from claims_agent.response.context import build_context
    from claims_agent.response.validator import ResponseValidator
    from claims_agent.state import ConversationState, Phase
    from tests.conftest import VERIFIED_P9
    scanner = PresidioScanner.try_create()
    if scanner is None:
        pytest.skip("presidio/spaCy model not installed")
    state = ConversationState(session_id="s", phase=Phase.PROCESS_CASE, verification=VERIFIED_P9,
                              selected_case_id="CL-2048")
    ctx = build_context(Decision(state=state, action=ControllerAction.ANSWER), repo)
    v = ResponseValidator(repo, pii_scanner=scanner)
    assert not v.validate("You can also reach the adjuster at someone@example.com.", [], ctx, "").ok
