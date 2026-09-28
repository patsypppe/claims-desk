"""Deterministic email summary assembled only from facts that were actually disclosed in the call."""
from claims_agent.domain.models import FrozenModel
from claims_agent.domain.repository import FixtureRepository
from claims_agent.grounding.facts import claim_detail_facts, derived_facts
from claims_agent.grounding.followup import document_guidance, join_documents, select_followup
from claims_agent.state import ConversationState


class EmailSummary(FrozenModel):
    subject: str
    body: str
    fact_ids: tuple[str, ...]


def _guidance_lines(repo: FixtureRepository, claim, disclosed: tuple[str, ...]) -> list[str]:
    lines = []
    for fact_id in disclosed:
        if not fact_id.startswith("guideline."):
            continue
        kind, rest = fact_id.split(".", 2)[1:]
        topic = rest.split("@")[0]
        if kind == "followup":
            entry = next((e for e in repo.guideline.claim_followup_guidance if e.topic == topic), None)
            if entry:
                g = select_followup(repo.guideline, claim, "none", " ".join(entry.match_any), topic,
                                    document_unavailable=topic == "missing_required_material_alternatives")
                lines.append(g.text if g else "")
        elif kind == "document":
            _, _, doc = topic.partition(":")
            lines.append(document_guidance(repo.guideline, claim, doc, topic.startswith("document_alternative")).text)
    return [line for line in dict.fromkeys(lines) if line]


def build_summary(repo: FixtureRepository, state: ConversationState, today) -> EmailSummary:
    disclosed = state.disclosed_fact_ids
    lines = ["Summary of your call with Claims Support", ""]
    used: list[str] = []
    claim = repo.claim(state.selected_case_id) if state.selected_case_id else None
    if claim is None:
        lines.append("We confirmed your identity and reviewed your account. No specific claim was discussed.")
    else:
        facts = {f.fact_id: f for f in claim_detail_facts(claim) + derived_facts(claim, today)}
        lines.append(f"Claim discussed: {claim.case_id} ({claim.case_type}, filed {facts[f'claims.{claim.case_id}.created_at'].display})")
        lines.append(f"Status: {claim.status}")
        used += [f"claims.{claim.case_id}.case_id", f"claims.{claim.case_id}.status"]
        if claim.denial_reason and f"claims.{claim.case_id}.denial_reason" in disclosed:
            lines.append(f"Reason on file: {claim.denial_reason}")
            used.append(f"claims.{claim.case_id}.denial_reason")
        if claim.documents_needed:
            lines.append(f"Documents still needed: {join_documents(claim.documents_needed)}")
        deadline = facts.get(f"derived.{claim.case_id}.appeal_deadline_status")
        if deadline:
            lines.append(f"Deadline: {deadline.display}")
            used.append(deadline.fact_id)
        guidance = _guidance_lines(repo, claim, disclosed)
        if guidance:
            lines += ["", "Guidance we discussed:", *[f"- {g}" for g in guidance]]
    if state.escalation.ticket_id:
        lines.append(f"Follow-up: a claims representative will contact you (reference {state.escalation.ticket_id}).")
    lines += ["", "Next steps: upload any requested documents through the member portal or claim upload link, "
                  "and contact us if anything is unclear."]
    subject = f"Your claim {claim.case_id} — call summary" if claim else "Your call summary"
    return EmailSummary(subject=subject, body="\n".join(lines), fact_ids=tuple(used))
