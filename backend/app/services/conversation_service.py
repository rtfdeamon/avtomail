from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import Conversation, Message
from app.models.enums import ConversationStatus, MessageDirection, MessageSender
from app.schemas import MessageSendRequest


class ConversationService:
    """Service layer for conversation and message workflows."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_conversations(self) -> Sequence[Conversation]:
        stmt: Select[Conversation] = (
            select(Conversation)
            .options(joinedload(Conversation.client))
            .order_by(Conversation.last_message_at.desc().nullslast())
        )
        conversations = (await self.session.scalars(stmt)).unique().all()
        return conversations

    async def get_conversation(self, conversation_id: int) -> Conversation:
        stmt: Select[Conversation] = (
            select(Conversation)
            .options(joinedload(Conversation.client), joinedload(Conversation.messages))
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
            sent_at=datetime.utcnow(),
            requires_attention=False,
            is_draft=False,
        )
        conversation.status = ConversationStatus.ANSWERED_BY_LLM
        conversation.last_message_at = message.sent_at
        conversation.last_message_preview = (payload.text or "")[:500]

        self.session.add(message)
        await self.session.flush()
        return message

    async def mark_needs_human(self, conversation: Conversation, draft_message: Message | None) -> None:
        conversation.status = ConversationStatus.NEEDS_HUMAN
        if draft_message:
            draft_message.requires_attention = True
            draft_message.is_draft = True
        await self.session.flush()

    async def register_inbound_message(self, conversation: Conversation, message: Message) -> None:
        conversation.status = ConversationStatus.AWAITING_RESPONSE
        conversation.last_message_at = message.received_at or message.created_at
        conversation.last_message_preview = (message.body_plain or message.body_html or "")[:500]
        await self.session.flush()

    async def close_conversation(self, conversation: Conversation) -> Conversation:
        conversation.status = ConversationStatus.CLOSED
        if conversation.last_message_at is None:
            conversation.last_message_at = datetime.utcnow()
        await self.session.flush()
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
