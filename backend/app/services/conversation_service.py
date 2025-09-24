from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import Conversation, Message
from app.models.enums import (
    ConversationActor,
    ConversationLogEvent,
    ConversationStatus,
    MessageDirection,
    MessageSender,
)
from app.models.log import ConversationLogEntry
from app.models.scenario import ConversationScenarioState, Scenario, ScenarioStep
from app.schemas import MessageSendRequest


class ConversationService:
    """Service layer for conversation and message workflows."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def _base_options(self):
        return (
            joinedload(Conversation.client),
            joinedload(Conversation.scenario_state)
            .joinedload(ConversationScenarioState.scenario)
            .joinedload(Scenario.steps),
            joinedload(Conversation.scenario_state).joinedload(ConversationScenarioState.active_step),

        )

    async def list_conversations(self) -> Sequence[Conversation]:
        stmt: Select[Conversation] = (
            select(Conversation)
            .options(*self._base_options())
            .order_by(Conversation.last_message_at.desc().nullslast())
        )
        conversations = (await self.session.scalars(stmt)).unique().all()
        return conversations

    async def get_conversation(self, conversation_id: int) -> Conversation:
        stmt: Select[Conversation] = (
            select(Conversation)
            .options(*self._base_options(), joinedload(Conversation.messages), joinedload(Conversation.logs))
            .where(Conversation.id == conversation_id)
        )
        conversation = (await self.session.scalars(stmt)).unique().one()
        return conversation

    async def record_outbound_message(
        self,
        conversation: Conversation,
        payload: MessageSendRequest,
        sender_type: MessageSender,
    ) -> Message:
        message = Message(
            conversation=conversation,
            sender_type=sender_type,
            direction=MessageDirection.OUTBOUND,
            body_plain=payload.text,
            subject=payload.subject or conversation.topic,
            sent_at=datetime.now(timezone.utc),
            requires_attention=False,
            is_draft=False,
        )
        conversation.status = ConversationStatus.ANSWERED_BY_LLM
        conversation.last_message_at = message.sent_at
        conversation.last_message_preview = (payload.text or "")[:500]

        self.session.add(message)
        await self.session.flush()

        actor = ConversationActor.MANAGER if sender_type == MessageSender.MANAGER else ConversationActor.ASSISTANT
        await self.log_event(
            conversation,
            ConversationLogEvent.MESSAGE_SENT,
            summary="Сообщение отправлено",
            actor=actor,
            details={"message_id": message.id, "subject": message.subject},
        )
        return message

    async def mark_needs_human(self, conversation: Conversation, draft_message: Message | None) -> None:
        conversation.status = ConversationStatus.NEEDS_HUMAN
        if draft_message:
            draft_message.requires_attention = True
            draft_message.is_draft = True
        await self.session.flush()
        await self.log_event(
            conversation,
            ConversationLogEvent.HUMAN_INTERVENTION_REQUIRED,
            summary="Требуется вмешательство оператора",
            actor=ConversationActor.SYSTEM,
        )

    async def register_inbound_message(self, conversation: Conversation, message: Message) -> None:
        conversation.status = ConversationStatus.AWAITING_RESPONSE
        conversation.last_message_at = message.received_at or message.created_at
        conversation.last_message_preview = (message.body_plain or message.body_html or "")[:500]
        await self.session.flush()
        await self.log_event(
            conversation,
            ConversationLogEvent.AUTOMATION_TRIGGERED,
            summary="Получено входящее письмо",
            actor=ConversationActor.CLIENT,
            details={"message_id": message.id, "subject": message.subject},
        )

    async def close_conversation(self, conversation: Conversation) -> Conversation:
        conversation.status = ConversationStatus.CLOSED
        if conversation.last_message_at is None:
            conversation.last_message_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.log_event(
            conversation,
            ConversationLogEvent.MESSAGE_SENT,
            summary="Переписка закрыта",
            actor=ConversationActor.SYSTEM,
        )
        return conversation

    async def unread_counts(self, conversation_ids: Sequence[int]) -> dict[int, int]:
        if not conversation_ids:
            return {}
        stmt = (
            select(
                Message.conversation_id,
                func.count(Message.id),
            )
            .where(
                Message.conversation_id.in_(conversation_ids),
                Message.direction == MessageDirection.INBOUND,
                Message.requires_attention.is_(True),
            )
            .group_by(Message.conversation_id)
        )
        rows = await self.session.execute(stmt)
        return {conversation_id: count for conversation_id, count in rows.all()}

    async def log_event(
        self,
        conversation: Conversation,
        event_type: ConversationLogEvent,
        summary: str,
        actor: ConversationActor = ConversationActor.SYSTEM,
        details: dict | None = None,
        context: str | None = None,
    ) -> ConversationLogEntry:
        entry = ConversationLogEntry(
            conversation=conversation,
            event_type=event_type,
            actor=actor,
            summary=summary[:500],
            details=details,
            context=context,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def assign_scenario(
        self,
        conversation: Conversation,
        scenario: Scenario,
        starting_step: ScenarioStep | None = None,
        notes: str | None = None,
    ) -> ConversationScenarioState:
        state = conversation.__dict__.get("scenario_state")
        if state is None:
            state = ConversationScenarioState(conversation=conversation)
            self.session.add(state)
        state.scenario = scenario
        if starting_step is None and scenario.steps:
            starting_step = min(scenario.steps, key=lambda step: step.order_index)
        state.active_step = starting_step
        state.notes = notes
        await self.session.flush()
        await self.log_event(
            conversation,
            ConversationLogEvent.SCENARIO_ASSIGNED,
            summary=f"Назначен сценарий '{scenario.name}'",
            actor=ConversationActor.SYSTEM,
            details={"scenario_id": scenario.id, "step_id": starting_step.id if starting_step else None},
        )
        return state

    async def advance_scenario_step(
        self,
        state: ConversationScenarioState,
        step: ScenarioStep | None = None,
        direction: str | None = None,
    ) -> ConversationScenarioState:
        scenario_steps = sorted(state.scenario.steps, key=lambda s: s.order_index)
        current_index = -1
        if state.active_step is not None:
            for idx, candidate in enumerate(scenario_steps):
                if candidate.id == state.active_step.id:
                    current_index = idx
                    break
        if step is not None:
            state.active_step = step
        elif direction == "previous" and current_index > 0:
            state.active_step = scenario_steps[current_index - 1]
        elif direction == "next" and current_index + 1 < len(scenario_steps):
            state.active_step = scenario_steps[current_index + 1]
        elif state.active_step is None and scenario_steps:
            state.active_step = scenario_steps[0]

        await self.session.flush()
        await self.log_event(
            state.conversation,
            ConversationLogEvent.SCENARIO_STEP_CHANGED,
            summary="Изменён этап сценария",
            actor=ConversationActor.SYSTEM,
            details={
                "scenario_id": state.scenario_id,
                "step_id": state.active_step.id if state.active_step else None,
            },
        )
        return state


