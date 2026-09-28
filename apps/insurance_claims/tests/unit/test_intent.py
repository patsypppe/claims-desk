import pytest

from claims_agent.intent import pick_option, resolve
from claims_agent.state import IntentHints


@pytest.fixture
def p9(repo):
    return repo.claims_for("P9")


def test_denied_january_healthcare_unique(p9):
    r = resolve(p9, IntentHints(case_type="healthcare", status="denied", month=1))
    assert (r.action, r.case_id) == ("PRESENT_CASE", "CL-2048")


def test_january_needs_disambiguation(p9):
    r = resolve(p9, IntentHints(case_type="healthcare", month=1))
    assert r.action == "DISAMBIGUATE_CASE" and set(r.candidates) == {"CL-2048", "CL-2011"}
    joined = " ".join(o.display for o in r.options)
    assert "1450" not in joined and "CL-" not in joined and "January 2026" in joined


def test_exact_claim_id(p9):
    assert resolve(p9, IntentHints(claim_id="CL-2102")).case_id == "CL-2102"


def test_other_party_claim_id_not_found(p9):
    assert resolve(p9, IntentHints(claim_id="CL-3001")).action == "NO_MATCHING_CASE"


def test_no_hints_asks_intent(p9):
    assert resolve(p9, IntentHints()).action == "ASK_INTENT"


def test_topic_only_asks_intent(p9):
    assert resolve(p9, IntentHints(topic="status_inquiry")).action == "ASK_INTENT"


def test_no_claims_customer(repo):
    assert resolve(repo.claims_for("P7"), IntentHints(case_type="healthcare")).action == "NO_CLAIMS"


def test_last_january(p9):
    assert resolve(p9, IntentHints(case_type="healthcare", month=1, year=2026)).case_id == "CL-2048"


def test_unmatched_filter_skipped_and_recorded(p9):
    r = resolve(p9, IntentHints(case_type="healthcare", status="denied", month=2))
    assert r.case_id == "CL-2048" and r.unmatched == ("month",)


def test_dental_november(p9):
    assert resolve(p9, IntentHints(case_type="dental", month=11)).case_id == "CL-1899"


def test_auto_accident(p9):
    assert resolve(p9, IntentHints(case_type="auto")).case_id == "CL-2102"


def test_pick_option_by_status_and_ordinal(p9):
    r = resolve(p9, IntentHints(case_type="healthcare", month=1))
    assert pick_option(r.options, IntentHints(status="denied"), "the denied one") == "CL-2048"
    assert pick_option(r.options, IntentHints(), "the second one") == r.options[1].case_id
    assert pick_option(r.options, IntentHints(year=2025), "the 2025 one") == "CL-2011"
    assert pick_option(r.options, IntentHints(), "not sure") is None
