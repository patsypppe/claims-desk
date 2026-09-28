import os
from datetime import date
from pathlib import Path

import pytest

from claims_agent.domain.repository import FixtureRepository

os.environ["CLAIMS_AGENT_SKIP_DOTENV"] = "1"  # tests never read the developer's real .env
FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"
TODAY = date(2026, 9, 28)


@pytest.fixture(scope="session")
def repo() -> FixtureRepository:
    return FixtureRepository.load(FIXTURES_DIR)


from claims_agent.clock import FixedClock  # noqa: E402
from claims_agent.state import ConsentState, ConversationState, Phase, Verification  # noqa: E402


def make_state(**updates) -> ConversationState:
    return ConversationState(session_id="test").model_copy(update=updates)


VERIFIED_P9 = Verification(verified=True, party_id="P9", method="self")


@pytest.fixture
def clock():
    return FixedClock(TODAY)


@pytest.fixture
def verified_margaret():
    return make_state(phase=Phase.RESOLVE_INTENT, verification=VERIFIED_P9)


@pytest.fixture
def margaret_process_case():
    return make_state(phase=Phase.PROCESS_CASE, verification=VERIFIED_P9, selected_case_id="CL-2048")


@pytest.fixture
def post_process_offered():
    return make_state(phase=Phase.POST_PROCESS, verification=VERIFIED_P9, selected_case_id="CL-2048",
                      consent=ConsentState.OFFERED, offer_id="offer-1")


@pytest.fixture
def post_process_granted(post_process_offered):
    return post_process_offered.model_copy(update={"consent": ConsentState.GRANTED})
