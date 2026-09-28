import pytest

from claims_agent.audit import mask
from claims_agent.state import ConversationState, LookupHints, ObservedValue
from claims_agent.verification import IdentityVerifier


@pytest.fixture
def verifier(repo):
    return IdentityVerifier(repo)


def state_with(policy=None, **fields):
    observed = tuple(ObservedValue(field=f, normalized=v, masked=mask(f, v), turn=1, source="rules")
                     for f, v in fields.items())
    return ConversationState(session_id="s", observed=observed, lookup=LookupHints(policy_number=policy))


@pytest.fixture
def V(verifier):
    return lambda **kw: verifier.evaluate(state_with(**kw))


def test_exactly_three_correct(V):
    assert V(name="Margaret Chen", dob="1985-03-15", id_last4="4472").party_id == "P9"


def test_five_correct(V):
    assert V(name="Margaret Chen", dob="1985-03-15", id_last4="4472", phone="+16505212836",
             email="margaret@email.com").status == "verified"


def test_one_field_insufficient(V):
    assert V(name="Margaret Chen").status == "insufficient"


def test_two_fields_insufficient(V):
    assert V(name="Margaret Chen", dob="1985-03-15").status == "insufficient"


def test_policy_not_a_factor(V):
    assert V(name="Margaret Chen", dob="1985-03-15", policy="POL-9921").status == "insufficient"


def test_wrong_dob_fails(V):
    assert V(name="Margaret Chen", dob="1985-03-16", id_last4="4472").status == "failed"


def test_wrong_ssn_fails(V):
    assert V(name="Margaret Chen", dob="1985-03-15", id_last4="4473").status == "failed"


def test_mixed_records_conflict(V):
    result = V(name="Margaret Chen", dob="1985-03-15", email="margaret@email.com", phone="+16505212830")
    assert result.status == "failed" and result.party_id is None


def test_policy_contradiction_fails(V):
    assert V(name="Margaret Chen", dob="1985-03-15", id_last4="4472", policy="POL-1044").status == "failed"


def test_matching_policy_allowed(V):
    assert V(name="Margaret Chen", dob="1985-03-15", id_last4="4472", policy="POL-9921").party_id == "P9"


def test_record_alias_name(V):
    assert V(name="Yaven Li", phone="+16505212830", email="yawen.li@example.com").party_id == "P13"


def test_duplicate_alias_counts_once(V):
    assert V(name="Yaven Li", email="yawen.li@example.com").status == "insufficient"


def test_surname_only_not_name(V):
    assert V(name="Chen", dob="1985-03-15", id_last4="4472").status == "failed"


def test_national_id_label_agnostic(V):
    assert V(name="Ma Tian", dob="1964-09-10", id_last4="6688").party_id == "P12"


def test_reversed_name_tokens(V):
    assert V(name="Tian Ma", dob="1964-09-10", id_last4="6688").party_id == "P12"


def test_knowledge_factor_option(repo):
    strict = IdentityVerifier(repo, require_knowledge_factor=True)
    s = state_with(name="Margaret Chen", phone="+16505212836", email="margaret@email.com")
    assert strict.evaluate(s).status == "insufficient"
    assert IdentityVerifier(repo).evaluate(s).status == "verified"


def test_failed_outcome_keeps_internal_candidate_for_lockout(V):
    assert V(name="Margaret Chen", dob="1985-03-16", id_last4="4472").candidate_party_id == "P9"


def test_failure_message_identical_across_mismatch_types(verifier):
    assert len({verifier.failure_message(r) for r in ["conflict", "no_match", "policy_mismatch"]}) == 1
