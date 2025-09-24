import pytest
from sqlalchemy import select

from app.models import Client, Conversation, Message, Scenario, ScenarioStep
from app.models.enums import (
    ConversationLogEvent,
    ConversationStatus,
    MessageDirection,
    MessageSender,
)
from app.schemas import MessageSendRequest
from app.services.conversation_service import ConversationService


@pytest.mark.asyncio
async def test_record_outbound_message_updates_conversation(session):
    client = Client(email="client@example.com", name="Client")
    conversation = Conversation(
        client=client,
        topic="Product inquiry",
        status=ConversationStatus.AWAITING_RESPONSE,
    )
    session.add_all([client, conversation])
    await session.flush()

    service = ConversationService(session)
    payload = MessageSendRequest(text="Hello there", send_mode="manual", subject=None)

    message = await service.record_outbound_message(conversation, payload, MessageSender.MANAGER)

    assert message.direction == MessageDirection.OUTBOUND
    assert message.body_plain == "Hello there"
    assert message.subject == "Product inquiry"
    assert message.sent_at is not None

    refreshed_conversation = await session.scalar(select(Conversation).where(Conversation.id == conversation.id))
    assert refreshed_conversation.status == ConversationStatus.ANSWERED_BY_LLM
    assert refreshed_conversation.last_message_preview.startswith("Hello there")

    await session.refresh(conversation, attribute_names=["logs"])
    assert conversation.logs
    assert conversation.logs[0].event_type == ConversationLogEvent.MESSAGE_SENT


@pytest.mark.asyncio
async def test_mark_needs_human_flags_draft(session):
    client = Client(email="client2@example.com", name="Client Two")
    conversation = Conversation(client=client, topic="Another topic")
    draft = Message(
        conversation=conversation,
        subject="Re: Another topic",
        sender_type=MessageSender.ASSISTANT,
        direction=MessageDirection.DRAFT,
        body_plain="Draft body",
        requires_attention=False,
        is_draft=False,
    )
    session.add_all([client, conversation, draft])
    await session.flush()

    service = ConversationService(session)
    await service.mark_needs_human(conversation, draft)

    refreshed_conversation = await session.scalar(select(Conversation).where(Conversation.id == conversation.id))
    refreshed_draft = await session.scalar(select(Message).where(Message.id == draft.id))

    assert refreshed_conversation.status == ConversationStatus.NEEDS_HUMAN
    assert refreshed_draft.requires_attention is True
    assert refreshed_draft.is_draft is True

    await session.refresh(conversation, attribute_names=["logs"])
    assert any(log.event_type == ConversationLogEvent.HUMAN_INTERVENTION_REQUIRED for log in conversation.logs)


@pytest.mark.asyncio
async def test_scenario_assignment_and_advance(session):
    client = Client(email="client3@example.com", name="Client Three")
    conversation = Conversation(client=client, topic="Scenario topic")
    scenario = Scenario(name="Demo scenario")
    step_one = ScenarioStep(scenario=scenario, order_index=1, title="Initial contact")
    step_two = ScenarioStep(scenario=scenario, order_index=2, title="Qualification")
    session.add_all([client, conversation, scenario, step_one, step_two])
    await session.flush()

    service = ConversationService(session)
    state = await service.assign_scenario(conversation, scenario)
    await session.flush()

    assert state.scenario_id == scenario.id
    assert state.active_step.id == step_one.id

    await service.advance_scenario_step(state, direction="next")
    await session.flush()
    assert state.active_step.id == step_two.id

    await session.refresh(conversation, attribute_names=["logs"])
    events = [log.event_type for log in conversation.logs]
    assert ConversationLogEvent.SCENARIO_ASSIGNED in events
    assert ConversationLogEvent.SCENARIO_STEP_CHANGED in events
