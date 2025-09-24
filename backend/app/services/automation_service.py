from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import Settings, get_settings
from app.core.logging import logger
from app.models import Client, Conversation, Message
from app.models.enums import ConversationStatus, MessageDirection, MessageSender
from app.schemas import MessageSendRequest
from app.services.conversation_service import ConversationService
from app.services.language_service import LanguageDetector
from app.services.llm_service import LLMRequest, LLMResponse, LLMService
from app.services.mail_service import InboundEmail, MailService, OutboundEmail


@dataclass(slots=True)
class AutomationResult:
    inbound_message_id: int
    outbound_message_id: int | None
    requires_human: bool


class AutomationService:
    """Coordinates inbound email processing, LLM drafting, and outbound delivery."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        mail_service: MailService | None = None,
        llm_service: LLMService | None = None,
        language_detector: LanguageDetector | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.mail_service = mail_service or MailService(self.settings)
        self.llm_service = llm_service or LLMService(self.settings)
        self.language_detector = language_detector or LanguageDetector(self.settings)
        self.conversation_service = ConversationService(session)

    # ------------------------------------------------------------------
    async def process_inbound(self, email: InboundEmail) -> AutomationResult:
        client = await self._get_or_create_client(email)
        conversation = await self._locate_conversation(client, email)
        language = self.language_detector.detect(email.body_plain or email.body_html or email.subject)
        if language:
            conversation.language = language

        inbound_message = await self._store_inbound_message(conversation, email, language)
        await self.session.flush()

        logger.info("Processing inbound email %s for conversation %s", email.message_id, conversation.id)
        llm_messages = await self._build_llm_messages(conversation)
        llm_request = LLMRequest(messages=llm_messages)
        llm_response = await self.llm_service.generate_reply(llm_request)
        logger.info(
            "LLM response generated for conversation %s (requires_human=%s)",
            conversation.id,
            llm_response.requires_human,
        )

        if not llm_response.content.strip():
            await self.conversation_service.mark_needs_human(conversation, None)
            await self.session.commit()
            return AutomationResult(
                inbound_message_id=inbound_message.id,
                outbound_message_id=None,
                requires_human=True,
            )

        subject = self._reply_subject(conversation.topic or email.subject or "")

        if llm_response.requires_human or not self.settings.auto_send_llm_replies:
            draft_message = await self._store_draft(conversation, subject, llm_response)
            await self.conversation_service.mark_needs_human(conversation, draft_message)
            logger.info("Conversation %s flagged for manual review", conversation.id)
            await self.session.commit()
            return AutomationResult(
                inbound_message_id=inbound_message.id,
                outbound_message_id=draft_message.id,
                requires_human=True,
            )

        try:
            outbound_message = await self._send_assistant_reply(
                conversation,
                subject,
                llm_response,
                email,
            )
        except Exception:
            await self.session.commit()
            return AutomationResult(
                inbound_message_id=inbound_message.id,
                outbound_message_id=None,
                requires_human=True,
            )

        logger.info("Auto reply sent for conversation %s", conversation.id)
        await self.session.commit()
        return AutomationResult(
            inbound_message_id=inbound_message.id,
            outbound_message_id=outbound_message.id,
            requires_human=False,
        )
    # ------------------------------------------------------------------
    async def _get_or_create_client(self, email: InboundEmail) -> Client:
        stmt = select(Client).where(Client.email == email.from_address.lower())
        client = await self.session.scalar(stmt)
        if client:
            if not client.name and email.from_name:
                client.name = email.from_name
            return client
        client = Client(email=email.from_address.lower(), name=email.from_name)
        self.session.add(client)
        await self.session.flush()
        return client

    async def _locate_conversation(self, client: Client, email: InboundEmail) -> Conversation:
        if email.in_reply_to:
            stmt = (
                select(Message)
                .options(joinedload(Message.conversation))
                .where(Message.external_id == email.in_reply_to)
            )
            message = await self.session.scalar(stmt)
            if message:
                return message.conversation

        topic = email.subject or "Без темы"
        stmt = (
            select(Conversation)
            .options(joinedload(Conversation.messages))
            .where(
                Conversation.client_id == client.id,
                Conversation.status != ConversationStatus.CLOSED,
            )
            .order_by(Conversation.updated_at.desc().nullslast())
        )
        result = await self.session.scalars(stmt)
        conversations = result.unique().all()
        for convo in conversations:
            if convo.topic == topic:
                return convo
        if conversations:
            return conversations[0]

        new_conversation = Conversation(
            client=client,
            topic=topic,
            status=ConversationStatus.AWAITING_RESPONSE,
            last_message_at=datetime.utcnow(),
            last_message_preview=email.body_plain or email.body_html,
        )
        self.session.add(new_conversation)
        await self.session.flush()
        return new_conversation
    async def _store_inbound_message(
        self,
        conversation: Conversation,
        email: InboundEmail,
        language: str | None,
    ) -> Message:
        message = Message(
            conversation=conversation,
            external_id=email.message_id,
            in_reply_to=email.in_reply_to,
            subject=email.subject,
            sender_type=MessageSender.CLIENT,
            direction=MessageDirection.INBOUND,
            sender_address=email.from_address,
            sender_display_name=email.from_name,
            body_plain=email.body_plain or self._html_to_text(email.body_html),
            body_html=email.body_html,
            received_at=email.date,
            detected_language=language,
            requires_attention=True,
            is_draft=False,
        )
        self.session.add(message)
        await self.conversation_service.register_inbound_message(conversation, message)
        return message

    async def _store_draft(
        self,
        conversation: Conversation,
        subject: str,
        llm_response: LLMResponse,
    ) -> Message:
        draft = Message(
            conversation=conversation,
            subject=subject,
            sender_type=MessageSender.ASSISTANT,
            direction=MessageDirection.DRAFT,
            body_plain=llm_response.content,
            body_html=self._plain_to_html(llm_response.content),
            detected_language=conversation.language,
            requires_attention=True,
            is_draft=True,
        )
        self.session.add(draft)
        await self.session.flush()
        return draft

    async def _send_assistant_reply(
        self,
        conversation: Conversation,
        subject: str,
        llm_response: LLMResponse,
        inbound: InboundEmail,
    ) -> Message:
        payload = MessageSendRequest(
            text=llm_response.content,
            subject=subject,
            send_mode="approve_ai",
        )
        message = await self.conversation_service.record_outbound_message(
            conversation,
            payload,
            MessageSender.ASSISTANT,
        )
        await self.session.flush()

        references = list(inbound.references)
        if inbound.message_id:
            references.append(inbound.message_id)

        outbound_email = OutboundEmail(
            to_addresses=[inbound.from_address],
            subject=subject,
            body_plain=llm_response.content,
            body_html=self._plain_to_html(llm_response.content),
            in_reply_to=inbound.message_id or inbound.in_reply_to,
            references=references,
        )
        try:
            await asyncio.to_thread(self.mail_service.send_email, outbound_email)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to send auto-reply for conversation %s: %s", conversation.id, exc)
            message.requires_attention = True
            await self.conversation_service.mark_needs_human(conversation, message)
            raise
        return message
    async def _build_llm_messages(self, conversation: Conversation) -> list[dict[str, str]]:
        system_message = {
            "role": "system",
            "content": self._system_prompt(conversation.language),
        }
        historical_messages: list[dict[str, str]] = [system_message]
        recent_messages = list(conversation.messages)[-6:]
        for message in recent_messages:
            content = message.body_plain or self._html_to_text(message.body_html)
            if not content:
                continue
            role = "assistant" if message.sender_type != MessageSender.CLIENT else "user"
            historical_messages.append({"role": role, "content": content})
        return historical_messages

    def _system_prompt(self, language: str | None) -> str:
        base_prompt = (
            "Ты виртуальный менеджер по продажам компании. "
            "Отвечай вежливо, кратко и по делу. "
            "Всегда отвечай на языке клиента. Если не уверен, начни ответ со слова 'MANAGER' и объясни, что требуется помощь менеджера."
        )
        if language and language.startswith("en"):
            base_prompt = (
                "You are a sales manager assistant. Respond politely, professionally, and concisely. "
                "Always answer in the customer's language. If you are unsure, start the reply with the word 'MANAGER' and explain why human help is needed."
            )
        return base_prompt

    def _reply_subject(self, subject: str) -> str:
        normalized = subject.strip()
        if not normalized:
            return "Re:"
        if normalized.lower().startswith("re:"):
            return normalized
        return f"Re: {normalized}"

    @staticmethod
    def _plain_to_html(text: str) -> str:
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return "<p>" + escaped.replace("

", "</p><p>").replace("
", "<br />") + "</p>"

    @staticmethod
    def _html_to_text(html: str | None) -> str | None:
        if not html:
            return None
        import re

        text = re.sub(r"<br\s*/?>", "
", html, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "

", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return text





