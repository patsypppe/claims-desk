"""Independent re-implementation of the ≥3-same-record verification rule.

Deliberately separate from claims_agent.verification so a bug in one is caught by the other.
Factors are expected pre-normalized (ISO dob, E.164 phone, lowercase email).
"""
from claims_agent.domain.repository import FixtureRepository

MIN_FACTORS = 3


def _name_tokens(name: str) -> frozenset[str]:
    return frozenset("".join(ch for ch in name.casefold() if ch.isalnum() or ch.isspace()).split())


def _matches(person, field: str, value: str) -> bool:
    if field == "name":
        names = (person.name, *person.name_aliases)
        return _name_tokens(value) in {_name_tokens(n) for n in names}
    if field == "dob":
        return value == person.dob.isoformat()
    if field == "phone":
        return value in (person.phone, *person.phone_aliases)
    if field == "email":
        return value.strip().lower() in {e.lower() for e in (person.email, *person.email_aliases)}
    if field == "id_last4":
        return value == person.id_last4
    return False


def oracle_verify(repo: FixtureRepository, factors: dict[str, str]) -> str | None:
    policy = factors.get("policy_number")
    pii = {k: v for k, v in factors.items() if k != "policy_number" and v}
    if len(pii) < MIN_FACTORS:
        return None
    for person in repo.policyholders:
        if policy and policy != person.policy_number:
            continue
        if all(_matches(person, field, value) for field, value in pii.items()):
            return person.party_id
    return None
