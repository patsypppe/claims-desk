"""Third-party callers. Unlisted third parties get a generic refusal that reveals nothing about the account."""
from claims_agent.controller import ControllerAction as A
from claims_agent.controller import Decision, StepContext
from claims_agent.state import ConversationState


def handle(ctx: StepContext, state: ConversationState) -> Decision:
    return ctx.decide(state.model_copy(update={"expected_field": None}), A.REFUSE_THIRD_PARTY)
