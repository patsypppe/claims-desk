import pytest

from claims_agent.controller import ControllerAction, Decision
from claims_agent.grounding.facts import claim_detail_facts, derived_facts, payout_facts
from claims_agent.response.context import build_context
from claims_agent.response.validator import ResponseValidator
from claims_agent.state import ConversationState, Phase
from tests.conftest import TODAY, VERIFIED_P9


@pytest.fixture
def ctx(repo):
    claim = repo.claim("CL-2048")
    state = ConversationState(session_id="s", phase=Phase.PROCESS_CASE, verification=VERIFIED_P9,
                              selected_case_id="CL-2048")
    facts = claim_detail_facts(claim) + derived_facts(claim, TODAY) + payout_facts(claim, repo.claim_schema)
    return build_context(Decision(state=state, action=ControllerAction.ANSWER, facts=facts), repo)


@pytest.fixture
def v(repo):
    return ResponseValidator(repo)


@pytest.mark.parametrize("reply", ["Once you send the documents, your claim will be approved.",
                                   "I guarantee the appeal will go through.",
                                   "It should definitely be overturned on appeal.",
                                   "It will probably be approved after review.",
                                   "I promise you'll be reimbursed."])
def test_promissory_language_rejected(v, ctx, reply):
    result = v.validate(reply, [], ctx, "")
    assert not result.ok and any(x.startswith("promissory") for x in result.violations)


@pytest.mark.parametrize("reply", ["I can't promise that a late submission will be accepted.",
                                   "There's no guarantee it will be approved, but a representative can review it.",
                                   "Because claim CL-2048 was denied, nothing will be paid on it right now.",
                                   "Please send the original pathology report and the office note."])
def test_negated_or_grounded_phrasing_allowed(v, ctx, reply):
    assert v.validate(reply, [], ctx, "").ok, v.validate(reply, [], ctx, "").violations


def test_hhem_wrapper_is_optional():
    from evals.hhem import grounding_score
    score = grounding_score(["Claim CL-2048 was denied."], "Your claim was denied.")
    assert score is None or 0.0 <= score <= 1.0


def test_conditional_promise_rejected(v, ctx):
    assert not v.validate("If you send the documents this week, your claim will be approved.", [], ctx, "").ok
