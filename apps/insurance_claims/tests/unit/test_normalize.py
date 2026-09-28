from datetime import date

import pytest

from claims_agent.normalize import (
    normalize_claim_id,
    normalize_dob,
    normalize_email,
    normalize_id_last4,
    normalize_name,
    normalize_phone,
    normalize_policy,
    parse_month_year,
)

T = date(2026, 9, 28)


@pytest.mark.parametrize("raw", ["1985-03-15", "March 15, 1985", "15 March 1985", "3/15/1985", "03/15/85",
                                 "March 15th 1985", "Mar 15 1985", "15th of March, 1985", "3-15-1985"])
def test_dob_formats(raw):
    assert normalize_dob(raw, T) == "1985-03-15"


def test_ambiguous_date_uses_us_order_only():
    assert normalize_dob("09/10/1964", T) == "1964-09-10"


@pytest.mark.parametrize("raw", ["13/45/1985", "February 30, 1990", "2030-01-01", "yesterday"])
def test_invalid_or_future_dob_rejected(raw):
    assert normalize_dob(raw, T) is None


@pytest.mark.parametrize("raw", ["(650) 521-2836", "650.521.2836", "+1 650 521 2836", "16505212836", "6505212836"])
def test_phone_formats(raw):
    assert normalize_phone(raw) == "+16505212836"


@pytest.mark.parametrize("raw", ["521-2836", "12345", "+44 20 7946 0958"])
def test_partial_or_foreign_phone_rejected(raw):
    assert normalize_phone(raw) is None


def test_email_normalized_without_gmail_folding():
    assert normalize_email("  MARGARET@Email.com ") == "margaret@email.com"
    assert normalize_email("ya.wen+x@gmail.com") == "ya.wen+x@gmail.com"
    assert normalize_email("not-an-email") is None


def test_name_normalized():
    assert normalize_name("  margaret   CHEN. ") == "margaret chen"


def test_id_last4():
    assert normalize_id_last4(" 44 72 ") == "4472"
    assert normalize_id_last4("447") is None


@pytest.mark.parametrize("raw", ["CL-2048", "cl 2048", "CL2048", "CL‑2048"])
def test_claim_id(raw):
    assert normalize_claim_id(raw) == "CL-2048"


def test_policy():
    assert normalize_policy("pol 9921") == "POL-9921"


@pytest.mark.parametrize("text,expected", [("from January", (1, None)), ("last January", (1, 2026)),
                                           ("January 2025", (1, 2025)), ("no month here", (None, None))])
def test_parse_month_year(text, expected):
    assert parse_month_year(text, T) == expected
