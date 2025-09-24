from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import NoResultFound

from app.models.enums import MessageSender
from app.schemas import ConversationDetail, ConversationSummary, MessageRead, MessageSendRequest
from app.services.conversation_service import ConversationService

from ..deps import get_conversation_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/", response_model=list[ConversationSummary])
async def list_conversations(
    service: ConversationService = Depends(get_conversation_service),
) -> list[ConversationSummary]:
    conversations = await service.list_conversations()
    unread_map = await service.unread_counts([conv.id for conv in conversations])
    return [
        ConversationSummary(
            id=conv.id,
            client=conv.client,
            topic=conv.topic,
            status=conv.status,
            last_message_at=conv.last_message_at,
            unread_count=unread_map.get(conv.id, 0),
        )
        for conv in conversations
    ]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationDetail:
    try:
        conversation = await service.get_conversation(conversation_id)
    except NoResultFound as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    messages = [
        MessageRead(
            id=message.id,
            sender_type=message.sender_type,
            direction=message.direction,
            subject=message.subject,
            body_plain=message.body_plain,
            body_html=message.body_html,
            detected_language=message.detected_language,
            sent_at=message.sent_at,
            received_at=message.received_at,
            requires_attention=message.requires_attention,
            is_draft=message.is_draft,
        )
        for message in conversation.messages
    ]
    return ConversationDetail(
        id=conversation.id,
        client=conversation.client,
        topic=conversation.topic,
        status=conversation.status,
        messages=messages,
    )


@router.post("/{conversation_id}/send", response_model=MessageRead)
async def send_message(
    conversation_id: int,
    payload: MessageSendRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> MessageRead:
    try:
        conversation = await service.get_conversation(conversation_id)
    except NoResultFound as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    sender_type = (
        MessageSender.ASSISTANT if payload.send_mode == "approve_ai" else MessageSender.MANAGER
    )

    message = await service.record_outbound_message(conversation, payload, sender_type)
    await service.session.commit()
    await service.session.refresh(message)

    return MessageRead(
        id=message.id,
        sender_type=message.sender_type,
        direction=message.direction,
        subject=message.subject,
        body_plain=message.body_plain,
        body_html=message.body_html,
        detected_language=message.detected_language,
        sent_at=message.sent_at,
        received_at=message.received_at,
        requires_attention=message.requires_attention,
        is_draft=message.is_draft,
    )


@router.post("/{conversation_id}/close", status_code=status.HTTP_204_NO_CONTENT)
async def close_conversation(
    conversation_id: int,
    service: ConversationService = Depends(get_conversation_service),
) -> None:
    try:
        conversation = await service.get_conversation(conversation_id)
    except NoResultFound as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    await service.close_conversation(conversation)
    await service.session.commit()


