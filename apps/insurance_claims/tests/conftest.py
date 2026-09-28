from datetime import date
from pathlib import Path

import pytest

from claims_agent.domain.repository import FixtureRepository

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
TODAY = date(2026, 9, 28)


@pytest.fixture(scope="session")
def repo() -> FixtureRepository:
    return FixtureRepository.load(FIXTURES_DIR)
