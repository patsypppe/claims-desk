"""Scenario file schema (YAML). One file per multi-turn conversation."""
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class TextExpect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    no_leak: bool = True
    must_reference: list[Any] = Field(default_factory=list)
    must_not_match: list[str] = Field(default_factory=list)
    must_not_reference: list[str] = Field(default_factory=list)
    asks_for_any: list[str] = Field(default_factory=list)
    no_ungrounded_atoms: bool = False


class TurnExpect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: dict[str, Any] = Field(default_factory=dict)
    tools_called: list[Any] = Field(default_factory=list)
    tools_not_called: list[str] = Field(default_factory=list)
    tools_blocked: list[str] = Field(default_factory=list)
    no_redundant_ask: list[str] = Field(default_factory=list)
    text: TextExpect = Field(default_factory=TextExpect)
    metric: list[str] = Field(default_factory=list)


class ScenarioTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user: str
    analysis: dict[str, Any] | None = None
    expect: TurnExpect = Field(default_factory=TurnExpect)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    category: str
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    clock: str = "2026-09-28"
    consent_scenario: str = "default"
    email_fails: bool = False
    otp_codes: list[str] | None = None
    verification_policy: str = "any3_or_otp"
    oracle_factors: dict[str, str] | None = None
    expected_outcome: dict[str, Any] = Field(default_factory=dict)
    turns: list[ScenarioTurn]


def load_scenarios(directory: Path, suite: str = "all") -> list[Scenario]:
    files = sorted(Path(directory).glob("*.yaml"))
    scenarios = [Scenario.model_validate(yaml.safe_load(f.read_text())) for f in files]
    if suite == "all":
        return scenarios
    return [s for s in scenarios if s.category == suite or suite in s.tags]
