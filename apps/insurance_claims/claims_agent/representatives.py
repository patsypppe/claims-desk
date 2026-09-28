"""Authorized-representative lookup (representatives.json). Name + relationship must both match."""
from claims_agent.domain.models import Representative
from claims_agent.domain.repository import FixtureRepository
from claims_agent.normalize import name_tokens
from claims_agent.state import Speaker

RELATIONSHIP_SYNONYMS = {"mom": "mother", "mum": "mother", "dad": "father", "hubby": "husband"}


def _relationship(value: str | None) -> str | None:
    return RELATIONSHIP_SYNONYMS.get((value or "").lower(), (value or "").lower() or None)


def listed_representative(repo: FixtureRepository, speaker: Speaker,
                          party_id: str | None = None) -> Representative | None:
    if not speaker.rep_name:
        return None
    for rep in repo.representatives:
        if party_id and rep.buyer_party_id != party_id:
            continue
        if name_tokens(rep.rep_name) == name_tokens(speaker.rep_name) and \
                _relationship(rep.relationship) == _relationship(speaker.relationship):
            return rep
    return None
