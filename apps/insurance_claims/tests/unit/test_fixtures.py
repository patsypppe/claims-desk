from decimal import Decimal

import pytest
from pydantic import ValidationError


def test_loads_all_policyholders(repo):
    assert {p.party_id for p in repo.policyholders} == {"P9", "P7", "P12", "P13"}


def test_claims_for_party_preserve_file_order(repo):
    assert [c.case_id for c in repo.claims_for("P9")] == ["CL-2048", "CL-2011", "CL-1899", "CL-2102"]


def test_party_without_claims_returns_empty_tuple(repo):
    assert repo.claims_for("P7") == ()


def test_claim_lookup_is_exact(repo):
    assert repo.claim("CL-2048").status == "denied"
    assert repo.claim("CL-9999") is None


def test_amounts_are_decimal(repo):
    assert repo.claim("CL-2048").allowed_max_amount == Decimal("1450.00")


def test_optional_claim_fields(repo):
    closed = repo.claim("CL-2011")
    assert closed.denial_reason is None and closed.documents_needed == () and closed.appeal_deadline is None


def test_policyholder_aliases_loaded(repo):
    ya_wen = repo.policyholder("P13")
    assert ya_wen.name_aliases == ("Yaven Li",) and ya_wen.email_aliases == ("yawen.li@example.com",)


def test_models_are_frozen(repo):
    with pytest.raises(ValidationError):
        repo.policyholders[0].name = "x"


def test_guideline_and_consent_loaded(repo):
    assert len(repo.guideline.claim_followup_guidance) == 6
    assert repo.consent_scenarios["timeout"] == ("pending",) * 5
    assert repo.representatives[0].rep_name == "David Chen"
