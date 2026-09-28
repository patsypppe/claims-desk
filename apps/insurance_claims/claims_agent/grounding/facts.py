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


def _long_date(d) -> str:
    return f"{MONTH_NAMES[d.month - 1]} {d.day}, {d.year}"


def derived_facts(claim: Claim, today) -> tuple[Fact, ...]:
    """Facts computed deterministically from claim data and the injectable clock."""
    if not claim.appeal_deadline:
        return ()
    base = f"derived.{claim.case_id}"
    days = (claim.appeal_deadline - today).days
    if days < 0:
        display = (f"The appeal deadline on file for this claim was {_long_date(claim.appeal_deadline)}, which has "
                   "already passed, so I can't promise that a late submission will be accepted.")
        return (Fact(fact_id=f"{base}.appeal_deadline_status", label="appeal_deadline_status", value="passed",
                     display=display),)
    display = (f"The appeal deadline on file is {_long_date(claim.appeal_deadline)}, which is {days} days from "
               "today.")
    return (Fact(fact_id=f"{base}.appeal_deadline_status", label="appeal_deadline_status",
                 value=f"{days} days remaining", display=display),)


def payout_facts(claim: Claim, schema) -> tuple[Fact, ...]:
    base = f"derived.{claim.case_id}.payout_explanation"
    allowed_desc = schema.field_descriptions["allowed_max_amount"].description.rstrip(".")
    if claim.status == "denied":
        text = (f"Because claim {claim.case_id} was denied, the payment on it is ${claim.net_pay:,.2f}. The allowed "
                f"maximum of ${claim.allowed_max_amount:,.2f} is {allowed_desc[0].lower() + allowed_desc[1:]}; "
                "it is not what will be paid.")
    elif claim.status == "open":
        text = (f"Claim {claim.case_id} is still open, so nothing has been paid yet (${claim.net_pay:,.2f} so far). "
                f"The expected reimbursement on file is ${claim.expected_reimbursement_amount:,.2f}, which is an "
                "estimate, not a final payment.")
    else:
        text = (f"The finalized payment on claim {claim.case_id} was ${claim.net_pay:,.2f}, against an allowed "
                f"maximum of ${claim.allowed_max_amount:,.2f}.")
    return (Fact(fact_id=base, label="answer", value=text, display=text),)


NOT_IN_DATA_NAMES = {"provider_or_facility": "the hospital or provider that submitted it",
                     "payment_date": "a payment date", "other": "that detail"}


def not_in_data_fact(claim: Claim, attribute: str) -> Fact:
    name = NOT_IN_DATA_NAMES.get(attribute, "that detail")
    text = (f"The claim record for {claim.case_id} doesn't include {name}, so I can't confirm it. A claims "
            "representative can look into it for you if you'd like.")
    return Fact(fact_id=f"not_in_data.{claim.case_id}.{attribute}", label="answer", value=text, display=text)
