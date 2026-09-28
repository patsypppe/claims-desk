import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from claims_agent.agent import build_agent_for_eval
from claims_agent.channel_auth import ChannelVerifier, mint
from tests.conftest import FIXTURES_DIR, TODAY

KEY = "test-signing-key-0123456789"


def test_valid_token_verifies_party():
    assert ChannelVerifier(KEY, now=lambda: 1000).verify(mint("P9", KEY, now=lambda: 1000)) == "P9"


@pytest.mark.parametrize("mutate", [lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"),
                                    lambda t: "x" + t, lambda t: t.replace(".", "")])
def test_tampered_token_rejected(mutate):
    assert ChannelVerifier(KEY, now=lambda: 1000).verify(mutate(mint("P9", KEY, now=lambda: 1000))) is None


def test_expired_wrong_key_and_replay_rejected():
    token = mint("P9", KEY, ttl=60, now=lambda: 1000)
    assert ChannelVerifier(KEY, now=lambda: 2000).verify(token) is None
    assert ChannelVerifier("other-key-000000000000", now=lambda: 1000).verify(token) is None
    v = ChannelVerifier(KEY, now=lambda: 1000)
    assert v.verify(token) == "P9" and v.verify(token) is None


def test_session_with_valid_channel_token_is_verified_on_first_turn(repo):
    agent = build_agent_for_eval(repo=repo, mode="rules", today=TODAY, channel_key=KEY)
    sid = agent.new_session(channel_token=mint("P9", KEY))
    r = agent.handle(sid, "Hi, it's about my denied healthcare claim")
    assert r.snapshot.verified and r.snapshot.verification_method == "channel"
    assert r.snapshot.selected_case_id == "CL-2048"


def test_bad_channel_token_falls_back_to_normal_verification(repo):
    agent = build_agent_for_eval(repo=repo, mode="rules", today=TODAY, channel_key=KEY)
    r = agent.handle(agent.new_session(channel_token="forged.token"), "Hi")
    assert not r.snapshot.verified and r.snapshot.phase == "VERIFY_ID"


def test_channel_tokens_ignored_when_feature_disabled(repo):
    agent = build_agent_for_eval(repo=repo, mode="rules", today=TODAY)
    r = agent.handle(agent.new_session(channel_token=mint("P9", KEY)), "Hi")
    assert not r.snapshot.verified


def test_api_accepts_channel_token():
    from claims_agent.api import create_app
    from claims_agent.config import Settings
    app = create_app(Settings(agent_mode="rules", app_today=TODAY, fixtures_dir=FIXTURES_DIR,
                              channel_signing_key=SecretStr(KEY)))
    c = TestClient(app)
    c.post("/api/session", json={"channel_token": mint("P9", KEY)})
    assert c.post("/api/chat", json={"text": "hi"}).json()["snapshot"]["verified"]
