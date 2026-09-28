"""Authorized-representative lookup (representatives.json). Name + relationship must both match."""
from claims_agent.domain.models import Representative
from claims_agent.domain.repository import FixtureRepository
from claims_agent.normalize import name_tokens
from claims_agent.state import Speaker

RELATIONSHIP_SYNONYMS = {"mom": "mother", "mum": "mother", "dad": "father", "hubby": "husband"}
# "my mother" (policyholder's relation to caller) implies the caller is her son or daughter, etc.
INVERSE = {"mother": {"son", "daughter"}, "father": {"son", "daughter"}, "parent": {"son", "daughter"},
           "son": {"mother", "father"}, "daughter": {"mother", "father"}, "wife": {"husband", "spouse"},
           "husband": {"wife", "spouse"}, "spouse": {"husband", "wife", "spouse"}}


def _relationship(value: str | None) -> str | None:
    return RELATIONSHIP_SYNONYMS.get((value or "").lower(), (value or "").lower() or None)


def listed_representative(repo: FixtureRepository, speaker: Speaker,
                          party_id: str | None = None) -> Representative | None:
    if not speaker.rep_name:
        return None
    for rep in repo.representatives:
        if party_id and rep.buyer_party_id != party_id:
            continue
        if name_tokens(rep.rep_name) != name_tokens(speaker.rep_name):
            continue
        listed = _relationship(rep.relationship)
        stated = _relationship(speaker.relationship)
        inferred = INVERSE.get(_relationship(speaker.subject_relation) or "", set())
        if (stated and stated == listed) or (not stated and listed in inferred):  # explicit statement wins
            return rep
    return None
