import pytest

from claims_agent.agent import build_agent_for_eval
from claims_agent.policy.emotion import strategy_for
from claims_agent.state import Phase
from tests.conftest import TODAY


@pytest.fixture
def agent(repo):
    return build_agent_for_eval(repo=repo, mode="rules", today=TODAY)


def talk(agent, *lines):
    sid = agent.new_session()
    return [agent.handle(sid, line) for line in lines]


def test_frustrated_unverified_still_gated(agent):
    _, r = talk(agent, "I'm Margaret Chen.",
                "I already told you who I am. This is ridiculous. Just tell me why my claim was denied.")
    assert r.snapshot.phase == Phase.VERIFY_ID and not r.snapshot.verified
    low = r.reply.lower()
    assert "frustrating" in low and "protected" in low and "date of birth" in low
    assert "denied" not in low


def test_repeated_anger_offers_human(agent):
    *_, r = talk(agent, "This is ridiculous!", "I already told you, this is unacceptable!!")
    assert "member of our team" in r.reply


def test_anxiety_reassures_with_next_step(agent):
    [r] = talk(agent, "I'm really worried, I think I missed my deadline")
    assert "step by step" in r.reply and "full name" in r.reply


def test_distrust_explains_protection_and_alternatives(agent):
    _, r = talk(agent, "Margaret Chen, DOB 1985-03-15", "Why do you need my SSN? This feels like a scam.")
    assert "last four" in r.reply and ("phone" in r.reply or "email" in r.reply)
    assert r.snapshot.phase == Phase.VERIFY_ID


def test_confusion_one_step(agent):
    [r] = talk(agent, "I'm confused, I don't understand what you need")
    assert "one step at a time" in r.reply


@pytest.mark.parametrize("label", ["neutral", "frustration", "anger", "anxiety", "confusion", "distrust"])
@pytest.mark.parametrize("intensity", ["low", "high"])
def test_strategy_is_pure_wording(label, intensity):
    s = strategy_for(label, intensity, 3)
    assert set(s.model_dump()) == {"label", "intensity", "steps", "offer_human", "max_sentences"}


def test_emotion_never_changes_phase_or_verification(agent):
    for text in ["This is ridiculous!!", "I'm so worried", "I'm confused", "Is this a scam?"]:
        [r] = talk(agent, text)
        assert r.snapshot.phase == Phase.VERIFY_ID and not r.snapshot.verified and not r.snapshot.escalated
