import pytest
from pydantic import ValidationError

from claims_agent.audit import mask
from claims_agent.state import ConversationState, ObservedValue, Phase, snapshot


def obs(field, value, turn, superseded=False):
    return ObservedValue(field=field, normalized=value, masked=mask(field, value), turn=turn,
                         source="rules", superseded=superseded)


def test_state_is_immutable():
    s = ConversationState(session_id="s1")
    with pytest.raises(ValidationError):
        s.phase = Phase.PROCESS_CASE


def test_current_ignores_superseded():
    s = ConversationState(session_id="s", observed=(obs("dob", "1985-03-16", 1, True), obs("dob", "1985-03-15", 2)))
    assert s.current("dob").normalized == "1985-03-15"


def test_current_values_one_per_field():
    s = ConversationState(session_id="s", observed=(obs("name", "Margaret Chen", 1), obs("dob", "1985-03-15", 1)))
    assert s.current_values() == {"name": "Margaret Chen", "dob": "1985-03-15"}


@pytest.mark.parametrize("field,value,masked", [
    ("name", "Margaret Chen", "M******* C***"), ("dob", "1985-03-15", "****-**-15"),
    ("phone", "+16505212836", "***-***-2836"), ("email", "margaret@email.com", "m*******@email.com"),
    ("id_last4", "4472", "**72")])
def test_mask(field, value, masked):
    assert mask(field, value) == masked


def test_snapshot_hides_party_before_verification():
    s = ConversationState(session_id="s", observed=(obs("id_last4", "4472", 1),))
    snap = snapshot(s)
    assert snap.verified_party_id is None and snap.captured_count == 1
    assert "4472" not in snap.model_dump_json()


def test_snapshot_shows_party_after_verification():
    s = ConversationState(session_id="s").model_copy(
        update={"verification": ConversationState.model_fields["verification"].default.model_copy(
            update={"verified": True, "party_id": "P9", "method": "self"})})
    assert snapshot(s).verified_party_id == "P9"
