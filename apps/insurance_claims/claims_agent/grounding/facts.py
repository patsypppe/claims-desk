"""Facts: the only unit of claim information that may reach a reply. Every fact carries provenance."""
from claims_agent.domain.models import Claim, FrozenModel

MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
               "October", "November", "December")


class Fact(FrozenModel):
    fact_id: str
    label: str
    value: str
    display: str


def month_year(claim: Claim) -> str:
    return f"{MONTH_NAMES[claim.created_at.month - 1]} {claim.created_at.year}"


def claim_option_facts(claim: Claim) -> tuple[Fact, ...]:
    """Minimal facts to let a verified caller pick among their own claims (no amounts)."""
    base = f"claims.{claim.case_id}"
    return (
        Fact(fact_id=f"{base}.case_id", label="case_id", value=claim.case_id, display=claim.case_id),
        Fact(fact_id=f"{base}.case_type", label="case_type", value=claim.case_type, display=claim.case_type),
        Fact(fact_id=f"{base}.created_at", label="created_at", value=claim.created_at.isoformat(),
             display=month_year(claim)),
        Fact(fact_id=f"{base}.status", label="status", value=claim.status, display=claim.status),
    )


def claim_detail_facts(claim: Claim) -> tuple[Fact, ...]:
    base = f"claims.{claim.case_id}"
    facts = list(claim_option_facts(claim))
    facts.append(Fact(fact_id=f"{base}.summary", label="summary", value=claim.summary, display=claim.summary))
    if claim.denial_reason:
        facts.append(Fact(fact_id=f"{base}.denial_reason", label="denial_reason", value=claim.denial_reason,
                          display=claim.denial_reason))
    for i, doc in enumerate(claim.documents_needed):
        facts.append(Fact(fact_id=f"{base}.documents_needed[{i}]", label="document_needed", value=doc, display=doc))
    if claim.appeal_deadline:
        facts.append(Fact(fact_id=f"{base}.appeal_deadline", label="appeal_deadline",
                          value=claim.appeal_deadline.isoformat(),
                          display=f"{MONTH_NAMES[claim.appeal_deadline.month - 1]} {claim.appeal_deadline.day}, "
                                  f"{claim.appeal_deadline.year}"))
    for name in ("expected_reimbursement_amount", "allowed_max_amount", "net_pay", "net_fee"):
        amount = getattr(claim, name)
        facts.append(Fact(fact_id=f"{base}.{name}", label=name, value=f"{amount:.2f}", display=f"${amount:,.2f}"))
    return tuple(facts)
