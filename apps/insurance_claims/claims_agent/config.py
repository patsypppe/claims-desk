"""Environment-driven settings. Fails fast with actionable messages."""
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import SecretStr

from claims_agent.clock import Clock, FixedClock, SystemClock

DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
AgentMode = Literal["llm", "rules"]


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a positive integer, got {raw!r}") from exc
    if value < 1:
        raise ConfigError(f"{name} must be a positive integer, got {raw!r}")
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _date_env(name: str) -> date | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an ISO date (YYYY-MM-DD), got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    agent_mode: AgentMode = "rules"
    api_key: SecretStr | None = field(default=None, repr=False)
    model: str = "claude-opus-5"
    extraction_model: str = "claude-opus-5"
    fixtures_dir: Path = DEFAULT_FIXTURES_DIR
    app_today: date | None = None
    consent_scenario: str = "default"
    max_verification_attempts: int = 3
    oos_offer_threshold: int = 2
    oos_escalation_threshold: int = 3
    max_clarifications: int = 3
    lockout_failures: int = 5
    require_knowledge_factor: bool = False
    debug_panel: bool = True
    session_ttl_minutes: int = 30

    def clock(self) -> Clock:
        return FixedClock(self.app_today) if self.app_today else SystemClock()

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.environ.get("AGENT_MODE", "llm").strip().lower()
        if mode not in ("llm", "rules"):
            raise ConfigError(f"AGENT_MODE must be 'llm' or 'rules', got {mode!r}")
        raw_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("AI_API_KEY")
        if mode == "llm" and not raw_key:
            raise ConfigError(
                "AGENT_MODE=llm requires ANTHROPIC_API_KEY (or AI_API_KEY). "
                "Set it in .env, or run with AGENT_MODE=rules for the deterministic no-LLM mode."
            )
        model = os.environ.get("AI_MODEL") or "claude-opus-5"
        return cls(
            agent_mode=mode,  # type: ignore[arg-type]
            api_key=SecretStr(raw_key) if raw_key else None,
            model=model,
            extraction_model=os.environ.get("AI_EXTRACTION_MODEL") or model,
            fixtures_dir=Path(os.environ.get("FIXTURES_DIR") or DEFAULT_FIXTURES_DIR),
            app_today=_date_env("APP_TODAY"),
            consent_scenario=os.environ.get("CONSENT_SCENARIO") or "default",
            max_verification_attempts=_int_env("MAX_VERIFICATION_ATTEMPTS", 3),
            oos_offer_threshold=_int_env("OOS_OFFER_THRESHOLD", 2),
            oos_escalation_threshold=_int_env("OOS_ESCALATION_THRESHOLD", 3),
            max_clarifications=_int_env("MAX_CLARIFICATIONS", 3),
            lockout_failures=_int_env("LOCKOUT_FAILURES", 5),
            require_knowledge_factor=_bool_env("REQUIRE_KNOWLEDGE_FACTOR", False),
            debug_panel=_bool_env("DEBUG_PANEL", True),
            session_ttl_minutes=_int_env("SESSION_TTL_MINUTES", 30),
        )
