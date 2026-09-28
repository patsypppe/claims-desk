"""Validated, immutable views over the starter fixtures."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Policyholder(FrozenModel):
    party_id: str
    name: str
    policy_number: str
    dob: date
    id_type: Literal["ssn_last4", "national_id_last4"]
    id_last4: str
    phone: str
    email: str
    name_aliases: tuple[str, ...] = ()
    phone_aliases: tuple[str, ...] = ()
    email_aliases: tuple[str, ...] = ()


class Claim(FrozenModel):
    case_id: str
    party_id: str
    case_type: Literal["healthcare", "dental", "auto"]
    created_at: date
    status: Literal["denied", "closed", "open"]
    summary: str
    denial_reason: str | None = None
    documents_needed: tuple[str, ...] = ()
    appeal_deadline: date | None = None
    expected_reimbursement_amount: Decimal
    allowed_max_amount: Decimal
    net_pay: Decimal
    net_fee: Decimal


class Representative(FrozenModel):
    rep_name: str
    relationship: str
    buyer_name: str
    buyer_party_id: str


class FollowupGuidance(FrozenModel):
    topic: str
    intent_hints: tuple[str, ...]
    requires_documents: bool
    match_any: tuple[str, ...] = ()
    en: str


class Guideline(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="ignore")
    default_guidance: dict[str, str]
    case_type_guidance: dict[str, dict[str, str]]
    document_guidance: dict[str, dict[str, str]]
    document_alternative_guidance: dict[str, dict[str, str]]
    claim_followup_settings: dict[str, dict[str, str]]
    claim_followup_guidance: tuple[FollowupGuidance, ...]
    claim_followup_fallback: dict[str, str]


class FieldDescription(FrozenModel):
    type: str
    example: str
    description: str


class ClaimSchema(FrozenModel):
    notes: tuple[str, ...]
    field_descriptions: dict[str, FieldDescription]
