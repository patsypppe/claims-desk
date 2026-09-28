import pytest

from claims_agent.agent import build_agent_for_eval
from claims_agent.sessions import SessionStore, UnknownSessionError
from tests.conftest import TODAY

WRONG = ["Margaret Chen, DOB 1985-03-16, SSN last four 4472", "DOB 1985-03-17", "DOB 1985-03-18"]


def test_unknown_session_rejected():
    with pytest.raises(UnknownSessionError):
        SessionStore().get("client-chosen")


def test_ttl_expiry_requires_new_session():
    clock = {"t": 0.0}
    store = SessionStore(ttl_seconds=10, now=lambda: clock["t"])
    sid = store.create()
    clock["t"] = 11.0
    with pytest.raises(UnknownSessionError):
        store.get(sid)


def test_reset_keeps_party_lockout(repo):
    agent = build_agent_for_eval(repo=repo, mode="rules", today=TODAY)
    s1 = agent.new_session()
    for line in WRONG:
        agent.handle(s1, line)
    s2 = agent.new_session()
    for line in WRONG[:2]:
        agent.handle(s2, line)
    s3 = agent.new_session()
    r = agent.handle(s3, "Margaret Chen, DOB 1985-03-15, SSN last four 4472")
    assert not r.snapshot.verified and r.snapshot.escalation_reason == "locked_out"


def test_other_customers_unaffected_by_lockout(repo):
    agent = build_agent_for_eval(repo=repo, mode="rules", today=TODAY)
    for _ in range(2):
        sid = agent.new_session()
        for line in WRONG:
            agent.handle(sid, line)
    r = agent.handle(agent.new_session(), "Ava Lopez, DOB 1990-08-21, SSN last four 9180")
    assert r.snapshot.verified
