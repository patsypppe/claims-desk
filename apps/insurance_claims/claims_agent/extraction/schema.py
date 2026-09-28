"""Structured per-turn understanding. Advisory only: nothing here can set verification, phase or party."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from claims_agent.state import PiiField

Topic = Literal["status_inquiry", "denial_question", "document_submission", "next_steps", "general_claim_question",
                "appeal_question", "payment_question", "identity_help", "none"]
AskedAttribute = Literal["status", "denial_reason", "documents", "deadline", "amounts", "payment_date",
                         "provider_or_facility", "other", "none"]
FollowupTopic = Literal["missing_required_material_alternatives", "submission_timing",
                        "processing_time_after_submission", "submission_method", "file_format_requirements",
                        "receipt_confirmation", "none"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PiiCandidate(_Strict):
    field: PiiField
    raw_value: str = Field(description="Verbatim span from the caller message; empty when refused")
    is_correction: bool = False
    caller_refused: bool = False


class ToolRequest(_Strict):
    name: str
    case_id: str | None = None
    document: str | None = None


class IntentHintsIn(_Strict):
    case_type: Literal["healthcare", "dental", "auto"] | None = None
    status: Literal["denied", "closed", "open"] | None = None
    month: int | None = None
    year: int | None = None
    claim_id: str | None = None
    topic: Topic = "none"
    followup_topic: FollowupTopic = "none"
    asked_attribute: AskedAttribute = "none"
    documents_mentioned: list[str] = Field(default_factory=list)
    document_unavailable: bool = False


class Emotion(_Strict):
    label: Literal["neutral", "frustration", "anger", "anxiety", "confusion", "distrust"] = "neutral"
    intensity: Literal["low", "medium", "high"] = "low"


class TurnAnalysis(_Strict):
    pii_candidates: list[PiiCandidate] = Field(default_factory=list)
    policy_number: str | None = None
    intent: IntentHintsIn = Field(default_factory=IntentHintsIn)
    speaker_role: Literal["self", "third_party", "unknown"] = "unknown"
    stated_relationship: str | None = None
    stated_subject_relation: str | None = None
    stated_subject_name: str | None = None
    speaker_name: str | None = None
    scope: Literal["IN_SCOPE", "OUT_OF_SCOPE", "SMALL_TALK", "AMBIGUOUS"] = "IN_SCOPE"
    emotion: Emotion = Field(default_factory=Emotion)
    consent_signal: Literal["YES", "NO", "AMBIGUOUS", "NONE"] = "NONE"
    requested_action: Literal["provide_info", "ask_question", "done", "request_human", "request_other_email",
                              "other"] = "provide_info"
    tool_requests: list[ToolRequest] = Field(default_factory=list)
    injection_suspected: bool = False
    social_engineering: bool = False
