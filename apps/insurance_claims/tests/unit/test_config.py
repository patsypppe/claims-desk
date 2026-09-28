from datetime import date

import pytest

from claims_agent.config import ConfigError, Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "AI_API_KEY", "AGENT_MODE", "APP_TODAY", "AI_MODEL"):
        monkeypatch.delenv(key, raising=False)


def test_llm_mode_without_key_fails_clearly(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "llm")
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        Settings.from_env()


def test_rules_mode_needs_no_key(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "rules")
    assert Settings.from_env().agent_mode == "rules"


def test_ai_api_key_alias(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "llm")
    monkeypatch.setenv("AI_API_KEY", "sk-test")
    assert Settings.from_env().api_key.get_secret_value() == "sk-test"


def test_key_never_in_repr(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "llm")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value")
    assert "sk-secret-value" not in repr(Settings.from_env())


def test_default_model(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "rules")
    assert Settings.from_env().model == "claude-opus-5"


def test_invalid_mode_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "yolo")
    with pytest.raises(ConfigError, match="AGENT_MODE"):
        Settings.from_env()


def test_app_today_pins_clock(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "rules")
    monkeypatch.setenv("APP_TODAY", "2026-09-28")
    assert Settings.from_env().clock().today() == date(2026, 9, 28)


def test_bad_threshold_rejected(monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "rules")
    monkeypatch.setenv("MAX_VERIFICATION_ATTEMPTS", "zero")
    with pytest.raises(ConfigError, match="MAX_VERIFICATION_ATTEMPTS"):
        Settings.from_env()
