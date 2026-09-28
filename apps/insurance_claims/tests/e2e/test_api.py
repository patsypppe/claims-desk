import pytest
from fastapi.testclient import TestClient

from claims_agent.api import create_app
from claims_agent.config import ConfigError, Settings
from tests.conftest import FIXTURES_DIR, TODAY

SAMPLE = ("I'm the policyholder. My name is Margaret Chen, policy POL-9921. I'm calling about my denied "
          "healthcare claim from January. DOB is 1985-03-15, SSN last four is 4472.")


@pytest.fixture
def client():
    return TestClient(create_app(Settings(agent_mode="rules", app_today=TODAY, fixtures_dir=FIXTURES_DIR)))


def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok", "mode": "rules"}


def test_chat_requires_server_session(client):
    assert client.post("/api/chat", json={"text": "hi"}).status_code == 401
    client.cookies.set("sid", "attacker-chosen")
    assert client.post("/api/chat", json={"text": "hi"}).status_code == 401


def test_sample_flow_and_debug_payload_masked(client):
    assert client.post("/api/session").status_code == 200
    body = client.post("/api/chat", json={"text": SAMPLE}).json()
    assert body["snapshot"]["phase"] == "PROCESS_CASE" and "CL-2048" in body["reply"]
    raw = str(body["snapshot"]) + str(body["events"])
    assert "4472" not in raw and "1985-03-15" not in raw and "margaret@email.com" not in raw
    assert "authorized_values" not in body


def test_reset_new_session(client):
    client.post("/api/session")
    first = client.cookies.get("sid")
    client.post("/api/chat", json={"text": "I'm Margaret Chen"})
    client.post("/api/reset")
    assert client.cookies.get("sid") != first
    assert client.post("/api/chat", json={"text": "hi"}).json()["snapshot"]["captured_count"] == 0


def test_input_too_long_rejected(client):
    client.post("/api/session")
    assert client.post("/api/chat", json={"text": "x" * 2001}).status_code == 422


def test_empty_input_rejected(client):
    client.post("/api/session")
    assert client.post("/api/chat", json={"text": "   "}).status_code == 422


def test_debug_panel_can_be_disabled():
    app = create_app(Settings(agent_mode="rules", app_today=TODAY, fixtures_dir=FIXTURES_DIR, debug_panel=False))
    c = TestClient(app)
    c.post("/api/session")
    body = c.post("/api/chat", json={"text": "hi"}).json()
    assert "snapshot" not in body and "events" not in body


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<title>" in r.text


def test_llm_mode_without_key_fails_startup(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_MODE", "llm")
    with pytest.raises(ConfigError):
        create_app()


def test_sensitive_flag_accepted(client):
    client.post("/api/session")
    body = client.post("/api/chat", json={"text": "4472", "sensitive": True}).json()
    assert body["snapshot"]["phase"] == "VERIFY_ID"


def test_ui_has_secure_entry_toggle(client):
    assert 'id="secure-toggle"' in client.get("/").text


def test_header_sessions_disabled_by_default(client):
    sid = client.post("/api/session").json().get("session_id")
    assert sid is None
    client.cookies.clear()
    assert client.post("/api/chat", json={"text": "hi"}, headers={"X-Session-Id": "anything"}).status_code == 401


def test_header_sessions_when_enabled_still_require_server_issued_ids():
    from claims_agent.api import create_app
    c = TestClient(create_app(Settings(agent_mode="rules", app_today=TODAY, fixtures_dir=FIXTURES_DIR,
                                       allow_header_sessions=True)))
    sid = c.post("/api/session").json()["session_id"]
    c.cookies.clear()
    assert c.post("/api/chat", json={"text": "hi"}, headers={"X-Session-Id": sid}).status_code == 200
    assert c.post("/api/chat", json={"text": "hi"}, headers={"X-Session-Id": "forged"}).status_code == 401
