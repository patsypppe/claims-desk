from datetime import date

import pytest

from claims_agent.grounding.facts import derived_facts, not_in_data_fact, payout_facts
from claims_agent.grounding.followup import (
    DOC_ALIASES,
    TemplateKeyError,
    document_guidance,
    fill_template,
    select_followup,
)
from tests.conftest import TODAY


@pytest.fixture
def cl2048(repo):
    return repo.claim("CL-2048")


def by_label(facts, label):
    return next(f for f in facts if f.label == label)


def test_every_documents_needed_has_alias_entry(repo):
    for claim in repo.claims:
        for doc in claim.documents_needed:
            assert doc in DOC_ALIASES


def test_alias_targets_exist_in_guideline(repo):
    for target in DOC_ALIASES.values():
        assert target is None or target in repo.guideline.document_guidance


def test_deadline_passed_fact(cl2048):
    fact = by_label(derived_facts(cl2048, TODAY), "appeal_deadline_status")
    assert fact.fact_id == "derived.CL-2048.appeal_deadline_status" and fact.value == "passed"
    assert "has already passed" in fact.display and "until" not in fact.display


def test_deadline_future(cl2048):
    fact = by_label(derived_facts(cl2048, date(2026, 3, 1)), "appeal_deadline_status")
    assert fact.value == "17 days remaining"


def test_no_deadline_no_fact(repo):
    assert derived_facts(repo.claim("CL-2011"), TODAY) == ()


def test_payout_never_presents_allowed_max_as_payment(cl2048, repo):
    text = " ".join(f.display for f in payout_facts(cl2048, repo.claim_schema))
    assert "$0.00" in text and "$1,450.00" in text and "not what will be paid" in text


def test_not_in_data_fact(cl2048):
    fact = not_in_data_fact(cl2048, "provider_or_facility")
    assert fact.fact_id == "not_in_data.CL-2048.provider_or_facility" and "doesn't include" in fact.display


def test_how_soon_to_submit_picks_submission_timing(repo, cl2048):
    g = select_followup(repo.guideline, cl2048, topic="document_submission", text="how soon do I need to submit these?")
    assert g.topic == "submission_timing" and "within a week" in g.text
    assert "pathology report and office note" in g.text


def test_bag_of_words_match_prefers_specific_entry(repo, cl2048):
    g = select_followup(repo.guideline, cl2048, topic="document_submission", text="What do I need to send and how soon?")
    assert g.topic == "submission_timing"


def test_how_long_after_submit_picks_processing(repo, cl2048):
    g = select_followup(repo.guideline, cl2048, topic="next_steps", text="how long does it take after I submit?")
    assert g.topic == "processing_time_after_submission" and "usually less than a week" in g.text


def test_submission_method(repo, cl2048):
    assert select_followup(repo.guideline, cl2048, "document_submission", "how do I submit them, is there a portal?").topic == "submission_method"


def test_unavailable_selects_alternatives_entry(repo, cl2048):
    g = select_followup(repo.guideline, cl2048, "document_submission", "I can't get it", document_unavailable=True)
    assert g.topic == "missing_required_material_alternatives"


def test_no_documents_claim_skips_document_entries(repo):
    assert select_followup(repo.guideline, repo.claim("CL-2102"), "next_steps", "how long does it take?") is None


def test_unavailable_doc_alternative(repo, cl2048):
    g = document_guidance(repo.guideline, cl2048, "pathology report", unavailable=True)
    assert "replacement copy" in g.text and g.topic == "document_alternative:original pathology report"


def test_doc_guidance_available(repo, cl2048):
    assert "visit date" in document_guidance(repo.guideline, cl2048, "office note", unavailable=False).text


def test_diagnosis_report_uses_default_guidance(repo):
    g = document_guidance(repo.guideline, repo.claim("CL-3001"), "diagnosis report", unavailable=False)
    assert "member portal" in g.text and "treating provider or facility name" in g.text


def test_template_unknown_key_raises():
    with pytest.raises(TemplateKeyError):
        fill_template("For {case_id} see {secret}", case_id="CL-1", documents="x", average_processing_time_after_submission="y")
