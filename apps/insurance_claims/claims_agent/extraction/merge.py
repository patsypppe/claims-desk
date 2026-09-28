"""Merge rule + LLM analyses, then fold the result into cross-phase memory.

Principle: extract now, act when authorized. Nothing in this module can change verification, phase,
selected case, consent or escalation — those belong to the controller.
"""
import re
from difflib import SequenceMatcher
from datetime import date

from claims_agent.audit import AuditEvent, mask
from claims_agent.extraction import lexicon as lx
from claims_agent.extraction.schema import IntentHintsIn, PiiCandidate, TurnAnalysis
from claims_agent.normalize import (
    MONTH_ALT,
    normalize_claim_id,
    normalize_dob,
    normalize_email,
    normalize_id_last4,
    normalize_name,
    normalize_phone,
    normalize_policy,
)
from claims_agent.state import ConversationState, IntentHints, ObservedValue

FORMATTED = frozenset({"dob", "phone", "email", "id_last4"})


def _collapse(text: str) -> str:
    return " ".join(text.casefold().split())


def _in_text(value: str | None, text: str) -> bool:
    return bool(value) and _collapse(value) in _collapse(text)


def _rejected(what: str, turn: int) -> AuditEvent:
    return AuditEvent(kind="llm_value_rejected", detail={"field": what, "reason": "not_in_caller_text"}, turn=turn)


def _merge_pii(rules: list[PiiCandidate], llm: list[PiiCandidate], text: str, turn: int):
    events: list[AuditEvent] = []
    kept_llm = []
    for c in llm:
        if c.caller_refused or _in_text(c.raw_value, text):
            kept_llm.append(c)
        else:
            events.append(_rejected(c.field, turn))
    rule_fields = {c.field for c in rules if not c.caller_refused}
    llm_names = [c for c in kept_llm if c.field == "name" and not c.caller_refused]
    merged = [c for c in rules if not (c.field == "name" and llm_names and not c.caller_refused)]
    for c in kept_llm:
        duplicate_refusal = c.caller_refused and any(r.caller_refused and r.field == c.field for r in merged)
        if c.caller_refused and not duplicate_refusal:
            merged.append(c)
        elif not c.caller_refused and (c.field == "name" or c.field not in rule_fields):
            merged.append(c)
    corrected = {c.field for c in rules + kept_llm if c.is_correction}
    merged = [c.model_copy(update={"is_correction": c.field in corrected}) for c in merged]
    return merged, events


def _without_dob(text: str, pii: list[PiiCandidate]) -> str:
    """The caller's text minus any date of birth, so a birth month/year never becomes a claim-date hint."""
    for c in pii:
        if c.field == "dob" and c.raw_value and c.raw_value in text:
            text = text.replace(c.raw_value, " ")
    return text


def _merge_intent(rules: IntentHintsIn, llm: IntentHintsIn, text: str, turn: int, events: list,
                  date_text: str | None = None) -> IntentHintsIn:
    claim_id = rules.claim_id
    if not claim_id and llm.claim_id:
        llm_id = normalize_claim_id(llm.claim_id)
        if llm_id is not None and llm_id == normalize_claim_id(text):  # None == None must not pass the gate
            claim_id = llm.claim_id
        else:
            events.append(_rejected("claim_id", turn))
    date_text = text if date_text is None else date_text
    month_word = bool(re.search(MONTH_ALT, date_text, re.I))
    pick = lambda r, l, default=None: l if l not in (None, "none", default) else r  # noqa: E731
    from claims_agent.extraction.lexicon import TYPE_SUPPORT

    llm_type = llm.case_type if llm.case_type and TYPE_SUPPORT[llm.case_type].search(text) else None
    llm_status = llm.status if llm.status in lx.STATUS_SUPPORT and lx.STATUS_SUPPORT[llm.status].search(text) else None
    return IntentHintsIn(
        case_type=rules.case_type or llm_type, status=pick(rules.status, llm_status),
        month=rules.month or (llm.month if month_word else None),
        year=rules.year or (llm.year if llm.year and str(llm.year) in date_text else None),
        claim_id=claim_id, topic=pick(rules.topic, llm.topic), followup_topic=pick(rules.followup_topic, llm.followup_topic),
        asked_attribute=pick(rules.asked_attribute, llm.asked_attribute),
        documents_mentioned=sorted({d for d in rules.documents_mentioned + llm.documents_mentioned if _in_text(d, text)}),
        document_unavailable=rules.document_unavailable or llm.document_unavailable,
        asked_attributes=list(dict.fromkeys(rules.asked_attributes + llm.asked_attributes)),
    )


def _merge_consent(rules: str, llm: str) -> str:
    if rules == llm:
        return rules
    if llm == "YES" and rules == "NONE":
        return "AMBIGUOUS"  # consent is an action gate: an affirmative must also be visible to the rules
    if "NO" in (rules, llm) and "YES" not in (rules, llm):
        return "NO"
    return "AMBIGUOUS" if "NONE" not in (rules, llm) or "AMBIGUOUS" in (rules, llm) else rules


PERSON_WORD_RE = re.compile(r"\b(human|person|people|someone|somebody|agent|representative|rep|manager|supervisor|"
                            r"operator|staff|team member|colleague|real person)\b", re.I)
EMAIL_EVIDENCE_RE = re.compile(r"[\w.+-]+@[\w-]+\.|\b(other|different|another|new|work|personal) (e-?mail|address)\b",
                               re.I)


def _merge_action(rules: str, llm: str, text: str, injection: bool) -> str:
    """High-impact actions need deterministic corroboration; an LLM label alone never escalates or re-routes."""
    if rules in ("repeat", "start_over", "skip"):
        return rules
    if "request_human" == rules or (llm == "request_human" and not injection and PERSON_WORD_RE.search(text)):
        return "request_human"
    if "request_other_email" == rules or (llm == "request_other_email" and EMAIL_EVIDENCE_RE.search(text)):
        return "request_other_email"
    if rules == "done" or (llm == "done" and "?" not in text):
        return "done"
    if llm in ("provide_info", "ask_question", "other"):
        return rules if rules in ("provide_info", "ask_question") else llm
    return rules


def _merge_scope(rules: TurnAnalysis, llm: TurnAnalysis, text: str, pii: list) -> str:
    """An LLM OUT_OF_SCOPE label only counts when nothing deterministic says the turn is in scope."""
    from claims_agent.extraction import lexicon as lx

    if llm.scope != "OUT_OF_SCOPE" or rules.scope == "OUT_OF_SCOPE":
        return llm.scope if llm.scope != "OUT_OF_SCOPE" else rules.scope
    in_scope_evidence = (lx.INSURANCE_RE.search(text) or rules.injection_suspected or llm.injection_suspected
                         or pii or rules.requested_action in ("done", "request_human")
                         or rules.consent_signal in ("YES", "NO") or re.search(r"\bverif", text, re.I))
    return rules.scope if in_scope_evidence else "OUT_OF_SCOPE"


def merge(*, rules: TurnAnalysis, llm: TurnAnalysis | None, text: str, today: date,
          turn: int = 0) -> tuple[TurnAnalysis, list[AuditEvent]]:
    if llm is None:
        return rules, []
    pii, events = _merge_pii(rules.pii_candidates, llm.pii_candidates, text, turn)
    policy = rules.policy_number
    if not policy and llm.policy_number:
        policy = llm.policy_number if normalize_policy(text) == normalize_policy(llm.policy_number) else None
    intent = _merge_intent(rules.intent, llm.intent, text, turn, events,
                           date_text=_without_dob(text, rules.pii_candidates + pii))
    relationship = rules.stated_relationship or (
        llm.stated_relationship if _in_text(llm.stated_relationship, text) else None)
    speaker = rules.speaker_name or (llm.speaker_name if _in_text(llm.speaker_name, text) else None)
    llm_role = llm.speaker_role
    if llm_role == "third_party" and rules.speaker_role != "third_party" and not lx.THIRD_PARTY_CUE_RE.search(text):
        llm_role = "unknown"  # sticky and locks the caller out: needs relation/behalf wording in the text
    third_party = "third_party" in (rules.speaker_role, llm_role)
    if speaker and third_party:  # a third-party caller's own name is never the policyholder's name factor
        from claims_agent.normalize import name_tokens
        pii = [c for c in pii if c.field != "name" or c.caller_refused or name_tokens(c.raw_value) != name_tokens(speaker)]
        if rules.stated_subject_name and not any(c.field == "name" and not c.caller_refused for c in pii):
            pii.append(PiiCandidate(field="name", raw_value=rules.stated_subject_name))
    merged = TurnAnalysis(
        pii_candidates=pii, policy_number=policy, intent=intent,
        speaker_role="third_party" if third_party
        else (llm_role if llm_role != "unknown" else rules.speaker_role),
        stated_relationship=relationship,
        stated_subject_relation=rules.stated_subject_relation or (
            llm.stated_subject_relation if _in_text(llm.stated_subject_relation, text) else None),
        stated_subject_name=rules.stated_subject_name or (
            llm.stated_subject_name if _in_text(llm.stated_subject_name, text) else None),
        speaker_name=speaker,
        scope=_merge_scope(rules, llm, text, pii), emotion=llm.emotion,
        consent_signal=_merge_consent(rules.consent_signal, llm.consent_signal),
        requested_action=_merge_action(rules.requested_action, llm.requested_action, text,
                                       rules.injection_suspected or llm.injection_suspected),
        tool_requests=rules.tool_requests + [t for t in llm.tool_requests
                                             if t.name not in {r.name for r in rules.tool_requests}],
        injection_suspected=rules.injection_suspected or llm.injection_suspected,
        wellbeing_risk=rules.wellbeing_risk or llm.wellbeing_risk,
        threat=rules.threat or (llm.threat and bool(lx.HOSTILE_CUE_RE.search(text))),
    )
    return merged, events


# ---- memory ----------------------------------------------------------------------------------------

def _normalizer(field: str, today: date):
    return {"dob": lambda v: normalize_dob(v, today), "phone": normalize_phone, "email": normalize_email,
            "id_last4": normalize_id_last4, "name": lambda v: normalize_name(v) or None}[field]


def _store_field(observed: tuple, field: str, value: str, turn: int, source: str) -> tuple:
    current = [o for o in observed if o.field == field and not o.superseded]
    if current and current[-1].normalized == value:
        return observed
    updated = tuple(o.model_copy(update={"superseded": True}) if o.field == field and not o.superseded else o
                    for o in observed)
    return updated + (ObservedValue(field=field, normalized=value, masked=mask(field, value), turn=turn,
                                    source=source),)


def _merge_hints(old: IntentHints, new: IntentHintsIn) -> IntentHints:
    updates = {k: getattr(new, k) for k in ("case_type", "status", "claim_id") if getattr(new, k)}
    if new.month:
        updates.update(month=new.month, year=new.year)
    elif new.year:
        updates["year"] = new.year
    if new.topic != "none":
        updates["topic"] = new.topic
    return old.model_copy(update=updates)


def _apply_pii(state: ConversationState, analysis: TurnAnalysis, turn: int, today: date):
    observed, refused, conflicts = state.observed, set(state.refused), []
    fields = {c.field for c in analysis.pii_candidates}
    for field in sorted(fields):
        cands = [c for c in analysis.pii_candidates if c.field == field]
        if any(c.caller_refused for c in cands):
            refused.add(field)
            continue
        values = list(dict.fromkeys(v for c in cands if (v := _normalizer(field, today)(c.raw_value))))
        if len(values) > 1 and not any(c.is_correction for c in cands):
            conflicts.append(field)
            continue
        if values:
            value = values[-1]
            current = state.current(field)
            if field == "name" and len(value.split()) == 1 and state.expected_field != "name":
                first = current.normalized.split()[0] if current and len(current.normalized.split()) >= 2 else None
                if first is None or SequenceMatcher(None, value.lower(), first.lower()).ratio() < 0.7:
                    continue  # "That's Ridiculous" / "it's Tuesday" is not a name correction
            if field == "name" and current and len(value.split()) == 1 and len(current.normalized.split()) >= 2:
                value = " ".join([value] + current.normalized.split()[1:])  # "that's Margaret" fixes the first name
            observed = _store_field(observed, field, value, turn, "rules")
            refused.discard(field)
    return observed, frozenset(refused), conflicts


def apply_analysis(state: ConversationState, analysis: TurnAnalysis, *, turn: int,
                   today: date) -> tuple[ConversationState, list[str]]:
    """Fold a merged analysis into memory. Returns (new_state, fields_with_conflicting_values)."""
    updates: dict = {"intent": _merge_hints(state.intent, analysis.intent)}
    conflicts: list[str] = []
    if not state.verification.verified:  # identity is frozen once verified (no write-back tools)
        observed, refused, conflicts = _apply_pii(state, analysis, turn, today)
        new_refusals = len(refused - state.refused)
        updates.update(observed=observed, refused=refused,
                       counters=state.counters.model_copy(
                           update={"refusals": state.counters.refusals + (1 if new_refusals else 0)}))
        if analysis.policy_number:
            updates["lookup"] = state.lookup.model_copy(update={"policy_number": normalize_policy(
                analysis.policy_number)})
    if analysis.speaker_role == "third_party" or state.speaker.role == "third_party":
        updates["speaker"] = state.speaker.model_copy(update={
            "role": "third_party",
            "rep_name": state.speaker.rep_name or analysis.speaker_name,
            "relationship": analysis.stated_relationship or state.speaker.relationship,
            "subject_relation": analysis.stated_subject_relation or state.speaker.subject_relation})
    elif analysis.speaker_role == "self" and state.speaker.role == "unknown":
        updates["speaker"] = state.speaker.model_copy(update={"role": "self"})
    return state.model_copy(update=updates), conflicts
