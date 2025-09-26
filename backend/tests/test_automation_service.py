from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models import Conversation, Message
from app.models.attachment import MessageAttachment
from app.models.enums import ConversationStatus, MessageDirection
from app.services.automation_service import AutomationService
from app.services.llm_service import LLMRequest, LLMResponse
from app.services.mail_service import EmailAttachment, InboundEmail, OutboundEmail


class StubLLMService:
    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.seen_requests: list[LLMRequest] = []

    async def generate_reply(self, request: LLMRequest) -> LLMResponse:
        self.seen_requests.append(request)
        return self.response


@dataclass
class StubLanguageDetector:
    detected_language: str = "en"

    def detect(self, text: str | None) -> str | None:
        return self.detected_language


class StubMailService:
    def __init__(self) -> None:
        self.sent: list[OutboundEmail] = []

    def send_email(self, email: OutboundEmail) -> None:
        self.sent.append(email)


def make_inbound_email(subject: str = "Initial question", body: str = "Hello", attachments: list[EmailAttachment] | None = None) -> InboundEmail:
    return InboundEmail(
        imap_uid=b"1",
        message_id="<msg-1>",
        subject=subject,
        from_address="client@example.com",
        from_name="Client",
        to_addresses=["[email protected]"],
        cc_addresses=[],
        date=datetime.now(timezone.utc),
        body_plain=body,
        body_html=None,
        in_reply_to=None,
        references=[],
        attachments=list(attachments or []),
        raw=b"",
    )


@pytest.mark.asyncio
async def test_process_inbound_requires_manual_review(session, tmp_path):
    settings = Settings(auto_send_llm_replies=True, enable_task_queue=False, attachments_dir=str(tmp_path / 'attachments'))
    mail_service = StubMailService()
    llm_service = StubLLMService(LLMResponse(content="MANAGER please", requires_human=True))
    language_detector = StubLanguageDetector("en")

    service = AutomationService(
        session,
        settings=settings,
        mail_service=mail_service,
        llm_service=llm_service,
        language_detector=language_detector,
    )

    result = await service.process_inbound(make_inbound_email())

    assert result.requires_human is True
    assert result.outbound_message_id is not None

    conversation = await session.scalar(select(Conversation))
    assert conversation is not None
    assert conversation.status == ConversationStatus.NEEDS_HUMAN

    messages = (await session.scalars(select(Message).order_by(Message.id))).all()
    assert len(messages) == 2  # inbound + draft
    draft = messages[-1]
    assert draft.direction == MessageDirection.DRAFT
    assert draft.requires_attention is True




@pytest.mark.asyncio
async def test_process_inbound_persists_attachments(session, tmp_path):
    settings = Settings(auto_send_llm_replies=True, enable_task_queue=False, attachments_dir=str(tmp_path / 'attachments'))
    mail_service = StubMailService()
    llm_service = StubLLMService(LLMResponse(content='MANAGER please', requires_human=True))
    language_detector = StubLanguageDetector('en')
    service = AutomationService(
        session,
        settings=settings,
        mail_service=mail_service,
        llm_service=llm_service,
        language_detector=language_detector,
    )

    attachment = EmailAttachment(filename='contract.txt', content_type='text/plain', content_id=None, payload=b'Hello', is_inline=False)
    await service.process_inbound(make_inbound_email(attachments=[attachment]))

    attachments = (await session.scalars(select(MessageAttachment))).all()
    assert len(attachments) == 1
    inbound_attachment = attachments[0]
    assert inbound_attachment.filename == 'contract.txt'
    assert inbound_attachment.file_size == 5
    stored_path = Path(settings.attachments_dir) / inbound_attachment.storage_path
    assert stored_path.exists()
@pytest.mark.asyncio
async def test_process_inbound_auto_sends_when_confident(session, tmp_path):
    settings = Settings(auto_send_llm_replies=True, enable_task_queue=False, attachments_dir=str(tmp_path / 'attachments'))
    mail_service = StubMailService()
    llm_service = StubLLMService(LLMResponse(content="Here is the answer", requires_human=False))
    language_detector = StubLanguageDetector("en")

    service = AutomationService(
        session,
        settings=settings,
        mail_service=mail_service,
        llm_service=llm_service,
        language_detector=language_detector,
    )

    result = await service.process_inbound(make_inbound_email(subject="Pricing"))

    assert result.requires_human is False
    assert result.outbound_message_id is not None
    assert len(mail_service.sent) == 1
    sent_email = mail_service.sent[0]
    assert sent_email.subject.startswith("Re:")

    conversation = await session.scalar(select(Conversation))
    assert conversation is not None
    assert conversation.status == ConversationStatus.ANSWERED_BY_LLM

    messages = (await session.scalars(select(Message))).all()
    assert any(message.direction == MessageDirection.OUTBOUND for message in messages)
