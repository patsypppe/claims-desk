import threading

import pytest
from fastapi.testclient import TestClient

from claims_agent.agent import build_agent_for_eval
from claims_agent.sessions import SessionStore, UnknownSessionError
from claims_agent.state import ConversationState, Phase
from claims_agent.storage.sqlite_store import SqliteLockoutRegistry, SqliteSessionStore
from tests.conftest import FIXTURES_DIR, TODAY

VERIFY = "Margaret Chen, born March 15 1985, SSN ends in 4472. It's about my denied healthcare claim."


def test_sqlite_state_survives_new_store_instance(tmp_path):
    db = tmp_path / "s.db"
    store = SqliteSessionStore(db, ttl_seconds=60)
    sid = store.create()
    store.save(ConversationState(session_id=sid, phase=Phase.RESOLVE_INTENT, refused=frozenset({"id_last4"})))
    again = SqliteSessionStore(db, ttl_seconds=60).get(sid)
    assert again.phase == Phase.RESOLVE_INTENT and again.refused == frozenset({"id_last4"})


def test_sqlite_unknown_and_expired_sessions(tmp_path):
    clock = {"t": 0.0}
    store = SqliteSessionStore(tmp_path / "s.db", ttl_seconds=10, now=lambda: clock["t"])
    with pytest.raises(UnknownSessionError):
        store.get("nope")
    sid = store.create()
    clock["t"] = 11
    with pytest.raises(UnknownSessionError):
        store.get(sid)


def test_sqlite_lockout_persists_across_instances(tmp_path):
    db = tmp_path / "s.db"
    for _ in range(5):
        SqliteLockoutRegistry(db).record_failure("P9")
    assert SqliteLockoutRegistry(db).is_locked("P9", 5) and not SqliteLockoutRegistry(db).is_locked("P7", 5)


def test_memory_store_prunes_expired():
    clock = {"t": 0.0}
    store = SessionStore(ttl_seconds=10, now=lambda: clock["t"])
    store.create()
    clock["t"] = 20
    assert store.prune() == 1


def test_concurrent_consent_sends_email_once(repo):
    agent = build_agent_for_eval(repo=repo, mode="rules", today=TODAY)
    sid = agent.new_session()
    agent.handle(sid, VERIFY)
    agent.handle(sid, "That's all.")
    threads = [threading.Thread(target=agent.handle, args=(sid, "Yes please send it.")) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(agent.controller.registry.email_sender.outbox) == 1


def test_verification_timing_is_padded(repo):
    slept = []
    agent = build_agent_for_eval(repo=repo, mode="rules", today=TODAY, verify_min_ms=400, sleeper=slept.append)
    agent.handle(agent.new_session(), "Margaret Chen, DOB 1985-03-16, SSN last four 4472")
    agent.handle(agent.new_session(), "Margaret Chen, DOB 1985-03-15, SSN last four 4472")
    assert len(slept) == 2 and all(s > 0 for s in slept)


def _client(**kw):
    from claims_agent.api import create_app
    from claims_agent.config import Settings
    return TestClient(create_app(Settings(agent_mode="rules", app_today=TODAY, fixtures_dir=FIXTURES_DIR, **kw)))


def test_session_creation_is_rate_limited_per_client():
    c = _client(session_create_limit=3)
    codes = [c.post("/api/session").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and 429 in codes[3:]


def test_secure_cookie_flag_configurable():
    r = _client(cookie_secure=True).post("/api/session")
    assert "secure" in r.headers["set-cookie"].lower()


def test_debug_payload_hides_validator_violation_details():
    c = _client()
    c.post("/api/session")
    events = c.post("/api/chat", json={"text": "hi"}).json()["events"]
    assert all("violations" not in e["detail"] for e in events)
