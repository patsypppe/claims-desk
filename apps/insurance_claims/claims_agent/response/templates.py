"""Deterministic replies for every controller action. Used in rules mode and as the validator fallback."""
from claims_agent.controller import ControllerAction as A
from claims_agent.response.context import ResponseContext
from claims_agent.verification import GENERIC_FAILURE

FIELD_LABELS = {"name": "your full name", "dob": "your date of birth", "phone": "the phone number on your policy",
                "email": "the email address on your policy",
                "id_last4": "the last four digits of your SSN or national ID"}
ACKNOWLEDGE = {
    "anger": "I understand this is frustrating, and I'm sorry you're having to repeat yourself.",
    "frustration": "I understand this is frustrating, and I'm sorry you're having to repeat yourself.",
    "anxiety": "I can hear this is stressful, and I'll help you sort it out step by step.",
    "confusion": "No problem, let me make this simpler.",
    "distrust": "That's a fair question, and I'm glad you asked.",
}
PROTECTED_EXPLANATION = ("Because claim details are protected, I need to verify your identity before I can "
                         "discuss them.")
ESCALATION_LEADS = {
    "caller_request": "Of course, I'll connect you with a member of our team.",
    "verification_failed": "I wasn't able to verify your identity, so I'm handing this over to a colleague who "
                           "can help with other options.",
    "insufficient_verification_factors": "I understand. Without enough verification details I can't discuss the "
                                         "account, so I'm connecting you with a colleague who can help.",
    "repeated_out_of_scope": "It sounds like you need help beyond what I can cover here, so I'm connecting you "
                             "with a member of our team.",
    "unresolved_ambiguity": "I want to make sure we look at the right claim, so I'm bringing in a colleague.",
    "tool_failure": "I'm having trouble reaching the claim system and don't want to give you incorrect "
                    "information, so I'm handing this to a colleague.",
    "locked_out": "For your security I can't continue verification on this line, so I'm connecting you with a "
                  "colleague.",
    "document_alternatives_exhausted": "Since the usual alternatives aren't available, a claims representative "
                                       "should review the file with you. I'm connecting you now.",
    "representative_consent_timeout": "I wasn't able to confirm the policyholder's authorization, so I'm "
                                      "connecting you with a colleague who can help.",
}


def _fact(ctx: ResponseContext, label: str) -> str | None:
    return next((f.display for f in ctx.facts if f.label == label), None)


def _facts(ctx: ResponseContext, label: str) -> list[str]:
    return [f.display for f in ctx.facts if f.label == label]


def join_list(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def _or_list(items: list[str]) -> str:
    labels = [FIELD_LABELS[i] for i in items]
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + f", or {labels[-1]}"


def _verified_prefix(ctx: ResponseContext) -> str:
    if not ctx.details.get("just_verified"):
        return ""
    return f"Thank you{', ' + ctx.caller_first_name if ctx.caller_first_name else ''}, you're verified. "


def _ask_fields(ctx: ResponseContext) -> str:
    field = ctx.required_elements[0] if ctx.required_elements else None
    parts = []
    if ctx.details.get("protected_request"):
        parts.append(PROTECTED_EXPLANATION)
    if ctx.details.get("captured", 0) == 0:
        parts.append(f"To get started, could you give me {FIELD_LABELS[field]}? I'll need three identifying "
                     "details in total, such as your full name, date of birth, and the last four digits of your "
                     "SSN or national ID.")
    else:
        extra = [a for a in ctx.alternatives if a != field]
        alt = f" (or, if you prefer, {_or_list(extra[:2])})" if extra else ""
        parts.append(f"Thank you. Could you also share {FIELD_LABELS[field]}{alt}?")
    return " ".join(parts)


def _offer_alt(ctx: ResponseContext) -> str:
    return f"That's okay, we can use a different verification detail instead. Could you share {_or_list(list(ctx.alternatives)[:2])}?"


def _present(ctx: ResponseContext) -> str:
    parts = [_verified_prefix(ctx)]
    if "month" in ctx.details.get("unmatched", []):
        parts.append("I didn't find a claim from the month you mentioned, but this looks like the closest match. ")
    parts.append(f"I found your {_fact(ctx, 'case_type')} claim {_fact(ctx, 'case_id')} from "
                 f"{_fact(ctx, 'created_at')}. Its current status is {_fact(ctx, 'status')}.")
    if reason := _fact(ctx, "denial_reason"):
        parts.append(f" The denial reason on file is that {reason}.")
    if docs := _facts(ctx, "document_needed"):
        parts.append(f" To have it reconsidered, the reviewer needs the {join_list(docs)}.")
    if deadline := _fact(ctx, "appeal_deadline_status"):
        parts.append(f" {deadline}")
    parts.append(" What would you like to know about it?")
    return "".join(parts)


def _sentences(ctx: ResponseContext) -> list[str]:
    by_id = {f.fact_id: f for f in ctx.facts}
    chosen = [by_id[i] for i in ctx.details.get("answer_ids", []) if i in by_id]
    lines, docs = [], [f.display for f in chosen if f.label == "document_needed"]
    for f in chosen:
        if f.label == "status":
            lines.append(f"Claim {_fact(ctx, 'case_id')} is currently {f.display}.")
        elif f.label == "denial_reason":
            lines.append(f"The denial reason on file is that {f.display}.")
        elif f.label != "document_needed":
            lines.append(f.display)
    if docs:
        lines.append(f"To have it reconsidered, the reviewer needs the {join_list(docs)}.")
    return lines


def _answer(ctx: ResponseContext) -> str:
    lines = _sentences(ctx) or [f"Claim {_fact(ctx, 'case_id')} is currently {_fact(ctx, 'status')}."]
    if ctx.details.get("offer_human"):
        return " ".join(lines) + " Would you like me to connect you with a claims representative?"
    return " ".join(lines) + " Is there anything else I can help you with on this claim?"


def _escalate(ctx: ResponseContext) -> str:
    lead = ESCALATION_LEADS.get(ctx.details.get("reason", ""), "I'm connecting you with a member of our team.")
    ref = _fact(ctx, "ticket_id")
    return f"{lead} Your reference is {ref}." if ref else lead


def _options(ctx: ResponseContext) -> str:
    return "; ".join(f"{i}. the {o}" for i, o in enumerate(ctx.options, start=1))


RENDERERS = {
    A.ASK_FIELDS: _ask_fields,
    A.OFFER_ALT_FIELD: _offer_alt,
    A.VERIFY_FAILED: lambda ctx: GENERIC_FAILURE,
    A.CONFIRM_CONFLICT: lambda ctx: f"I heard two different values for {FIELD_LABELS[ctx.details['field']]}. "
                                    "Which one is correct?",
    A.REFUSE_THIRD_PARTY: lambda ctx: ("I'm sorry, I can only discuss an account with the policyholder or a "
                                       "representative they've authorized. If the policyholder can join the call "
                                       "I'm happy to help, or I can connect you with a member of our team."),
    A.ASK_INTENT: lambda ctx: f"{_verified_prefix(ctx)}What can I help you with today? I see these claims on your "
                              f"account: {_options(ctx)}.",
    A.DISAMBIGUATE_CASE: lambda ctx: f"{_verified_prefix(ctx)}I found more than one claim that could match: "
                                     f"{_options(ctx)}. Which one would you like to discuss?",
    A.NO_MATCHING_CASE: lambda ctx: f"{_verified_prefix(ctx)}I don't see that claim on your account. Here's what I "
                                    f"do see: {_options(ctx)}. Which one would you like to discuss?",
    A.NO_CLAIMS: lambda ctx: f"{_verified_prefix(ctx)}I don't see any claims on your account right now. Is there "
                             "anything else I can help you with?",
    A.PRESENT_CASE: _present,
    A.ANSWER: _answer,
    A.NOT_IN_DATA: _answer,
    A.OFFER_EMAIL: lambda ctx: (f"Would you like me to email a summary of today's call to the address on file "
                                f"({ctx.masked_email})? Just say yes to send it or no to skip it."),
    A.CLARIFY_CONSENT: lambda ctx: (f"Just to confirm: should I email the summary to {ctx.masked_email}? "
                                    "Please answer yes or no."),
    A.EMAIL_SENT: lambda ctx: f"Done. I've emailed the summary to {ctx.masked_email}. Thanks for calling!",
    A.EMAIL_FAILED: lambda ctx: ("I'm sorry, the summary email couldn't be sent just now, so nothing was sent. "
                                 "Would you like me to try again?"),
    A.EMAIL_SKIPPED: lambda ctx: "No problem, I won't send an email. Thanks for calling, and take care!",
    A.REDIRECT_SCOPE: lambda ctx: ("I can help with your insurance policy or claim, but I can't assist with that "
                                   "topic. If you'd like, we can continue with your claim."),
    A.REFUSE_UNSAFE: lambda ctx: ("I can't help with that request. I'm here to help with your insurance policy "
                                  "or claim, and I'm happy to continue with that."),
    A.ESCALATE: _escalate,
    A.ESCALATED_HOLD: lambda ctx: ("A member of our team will pick this up from here, so I'm not able to continue "
                                   "on this line. Thank you for your patience."),
    A.CLOSE: lambda ctx: "Thanks for calling. If you need anything else, please start a new conversation.",
    A.REP_CONSENT_PENDING: lambda ctx: ("I've sent an authorization request to the policyholder's contact details "
                                        "on file. Once they approve it, I can continue."),
}


def emotion_prefix(ctx: ResponseContext) -> str:
    if ctx.emotion.label == "neutral" or "acknowledge" not in ctx.emotion.steps:
        return ""
    return ACKNOWLEDGE.get(ctx.emotion.label, "") + " "


def render(ctx: ResponseContext) -> str:
    body = RENDERERS[ctx.action](ctx)
    suffix = ""
    if ctx.emotion.offer_human and ctx.action not in (A.ESCALATE, A.ESCALATED_HOLD):
        suffix = " If you'd prefer, I can also connect you with a member of our team."
    return (emotion_prefix(ctx) + body + suffix).strip()
