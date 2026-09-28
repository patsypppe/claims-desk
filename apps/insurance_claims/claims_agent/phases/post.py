"""POST_PROCESS: optional email summary, sent only on explicit consent."""
import uuid

from claims_agent.controller import ControllerAction as A
from claims_agent.controller import Decision, StepContext
from claims_agent.state import ConsentState, ConversationState, Phase


def enter(ctx: StepContext, state: ConversationState) -> Decision:
    state = ctx.transition(state, Phase.POST_PROCESS, "case_handled")
    state = state.model_copy(update={"consent": ConsentState.OFFERED, "offer_id": uuid.uuid4().hex[:8],
                                     "awaiting_anything_else": False})
    return ctx.decide(state, A.OFFER_EMAIL)


def handle(ctx: StepContext, state: ConversationState) -> Decision:
    return ctx.decide(state, A.OFFER_EMAIL)
