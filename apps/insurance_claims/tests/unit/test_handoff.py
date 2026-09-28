from claims_agent.agent import build_agent_for_eval
from tests.conftest import TODAY

VERIFY = "Margaret Chen, born March 15 1985, SSN ends in 4472. It's about my denied healthcare claim."
DAVID = ("I'm David Chen, calling for my mother Margaret Chen, I'm her son. Her date of birth is 1985-03-15 "
         "and her SSN last four is 4472.")


def run(repo, *lines):
    agent = build_agent_for_eval(repo=repo, mode="rules", today=TODAY)
    sid = agent.new_session()
    results = [agent.handle(sid, line) for line in lines]
    return agent, results


def test_verification_record_event_documents_method_and_factors(repo):
    _, [r] = run(repo, VERIFY)
    record = next(e for e in r.events if e.kind == "verification_record")
    assert record.detail["method"] == "self" and sorted(record.detail["factors"]) == ["dob", "id_last4", "name"]
    assert "4472" not in str(record.detail) and "1985" not in str(record.detail)


def test_warm_handoff_carries_masked_summary_and_verification(repo):
    agent, _ = run(repo, VERIFY, "Can I talk to a real person please?")
    ticket = agent.controller.registry.handoff.tickets[-1]
    assert ticket["verification"]["method"] == "self" and ticket["verification"]["factors"]["id_last4"] == "**72"
    assert "CL-2048" in ticket["case_summary"] and "4472" not in str(ticket) and "1985-03-15" not in str(ticket)
    assert ticket["reason"] == "caller_request"


def test_handoff_records_representative_authority(repo):
    agent, _ = run(repo, DAVID, "I'd like to speak to a representative")
    rep = agent.controller.registry.handoff.tickets[-1]["verification"]["representative"]
    assert rep == {"name": "David Chen", "relationship": "son", "policyholder_consent": "approved"}


def test_unverified_handoff_has_no_case_summary(repo):
    agent, _ = run(repo, "I want to talk to a human")
    ticket = agent.controller.registry.handoff.tickets[-1]
    assert ticket["case_summary"] is None and ticket["verification"]["method"] is None
