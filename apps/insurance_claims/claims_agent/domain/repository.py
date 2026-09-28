"""Read-only fixture repository. Loaded once, validated on load."""
import json
from dataclasses import dataclass
from pathlib import Path

from claims_agent.domain.models import (
    Claim,
    ClaimSchema,
    Guideline,
    Policyholder,
    Representative,
)


class FixtureError(RuntimeError):
    """Raised when fixture files are missing or malformed."""


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FixtureError(f"Missing fixture file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FixtureError(f"Malformed JSON in {path}: {exc}") from exc


@dataclass(frozen=True)
class FixtureRepository:
    policyholders: tuple[Policyholder, ...]
    claims: tuple[Claim, ...]
    representatives: tuple[Representative, ...]
    guideline: Guideline
    claim_schema: ClaimSchema
    consent_scenarios: dict[str, tuple[str, ...]]

    @classmethod
    def load(cls, fixtures_dir: Path) -> "FixtureRepository":
        root = Path(fixtures_dir)
        consent_raw = _read_json(root / "consent_scenarios.json")
        return cls(
            policyholders=tuple(Policyholder(**p) for p in _read_json(root / "policyholders.json")),
            claims=tuple(Claim(**c) for c in _read_json(root / "claims.json")),
            representatives=tuple(Representative(**r) for r in _read_json(root / "representatives.json")),
            guideline=Guideline(**_read_json(root / "required_document_guideline.json")),
            claim_schema=ClaimSchema(**_read_json(root / "claim_schema.json")),
            consent_scenarios={k: tuple(v["status_sequence"]) for k, v in consent_raw.items()},
        )

    def policyholder(self, party_id: str) -> Policyholder | None:
        return next((p for p in self.policyholders if p.party_id == party_id), None)

    def claims_for(self, party_id: str) -> tuple[Claim, ...]:
        return tuple(c for c in self.claims if c.party_id == party_id)

    def claim(self, case_id: str) -> Claim | None:
        return next((c for c in self.claims if c.case_id == case_id), None)
