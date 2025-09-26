from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from celery.exceptions import CeleryError, TimeoutError

from app.core.config import Settings, get_settings
from app.core.logging import logger
from app.models import Client, Conversation, Message
from app.models.attachment import MessageAttachment
from app.models.scenario import ConversationScenarioState, Scenario, ScenarioStep
from app.models.enums import ConversationActor, ConversationLogEvent, ConversationStatus, MessageDirection, MessageSender
from app.schemas import MessageSendRequest
from app.services.attachment_service import AttachmentService, AttachmentTooLargeError
from app.services.conversation_service import ConversationService
from app.services.language_service import LanguageDetector
from app.services.llm_service import LLMRequest, LLMResponse, LLMService
from app.services.mail_service import EmailAttachment, InboundEmail, MailService, OutboundEmail
from app.workers.tasks import generate_llm_reply_task, send_email_task


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
        self.attachment_service = AttachmentService(self.settings)
        self.queue_enabled = self.settings.enable_task_queue

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
        llm_response = await self._generate_reply(llm_request)
        logger.info(
            "LLM response generated for conversation %s (requires_human=%s)",
            conversation.id,
            llm_response.requires_human,
        )
        await self.conversation_service.log_event(
            conversation,
            ConversationLogEvent.LLM_DRAFT_CREATED,
            summary="LLM draft generated",
            actor=ConversationActor.ASSISTANT,
            details={"requires_human": llm_response.requires_human},
            context=llm_response.content,
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
                .where(Message.external_id == email.in_reply_to)
            )
            message = await self.session.scalar(stmt)
            if message:
                return await self.conversation_service.get_conversation(message.conversation_id)

        topic = email.subject or "New conversation"
        stmt = (
            select(Conversation)
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
                return await self.conversation_service.get_conversation(convo.id)
        if conversations:
            return await self.conversation_service.get_conversation(conversations[0].id)

        new_conversation = Conversation(
            client=client,
            topic=topic,
            status=ConversationStatus.AWAITING_RESPONSE,
            last_message_at=datetime.now(timezone.utc),
            last_message_preview=email.body_plain or email.body_html,
        )
        self.session.add(new_conversation)
        await self.session.flush()
        return new_conversation
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
        await self.session.flush()
        await self._store_inbound_attachments(conversation, message, email.attachments)
        return message

    async def _store_inbound_attachments(
        self,
        conversation: Conversation,
        message: Message,
        attachments: list[EmailAttachment],
    ) -> None:
        if not attachments:
            return
        for attachment in attachments:
            try:
                storage_path, size = await self.attachment_service.save_bytes(
                    conversation.id,
                    attachment.filename,
                    attachment.payload,
                )
            except AttachmentTooLargeError as exc:
                logger.warning(
                    'Skipping attachment %s for conversation %s: %s',
                    attachment.filename,
                    conversation.id,
                    exc,
                )
                continue
            record = MessageAttachment(
                conversation_id=conversation.id,
                message=message,
                filename=attachment.filename,
                content_type=attachment.content_type,
                file_size=size,
                storage_path=storage_path,
                is_inline=attachment.is_inline,
                is_inbound=True,
            )
            self.session.add(record)
        await self.session.flush()

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
            await self._dispatch_email(outbound_email)
        except Exception as exc:  # pragma: no cover - network failure path
            logger.exception("Failed to send auto-reply for conversation %s: %s", conversation.id, exc)
            message.requires_attention = True
            await self.conversation_service.mark_needs_human(conversation, message)
            raise
        return message

    async def _generate_reply(self, request: LLMRequest) -> LLMResponse:
        if not self.queue_enabled:
            return await self.llm_service.generate_reply(request)
        try:
            return await self._generate_reply_via_queue(request)
        except (TimeoutError, CeleryError) as exc:
            logger.warning('Queue LLM execution failed (%s); falling back to inline call', exc)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning('Unexpected queue failure; falling back to inline call: %s', exc)
        return await self.llm_service.generate_reply(request)

    async def _generate_reply_via_queue(self, request: LLMRequest) -> LLMResponse:
        payload: dict[str, Any] = {
            'messages': [dict(message) for message in request.messages],
            'temperature': request.temperature,
            'max_tokens': request.max_tokens,
        }
        result = await self._apply_task(generate_llm_reply_task, payload, timeout=180)
        return LLMResponse(
            content=result.get('content', ''),
            requires_human=bool(result.get('requires_human')),
            raw=result.get('raw'),
        )

    async def _dispatch_email(self, email: OutboundEmail) -> None:
        if not self.queue_enabled:
            await asyncio.to_thread(self.mail_service.send_email, email)
            return
        payload = self._serialize_email(email)
        try:
            await self._apply_task(send_email_task, payload, timeout=180)
        except (TimeoutError, CeleryError) as exc:
            logger.warning('Queue email send failed (%s); retrying inline', exc)
            await asyncio.to_thread(self.mail_service.send_email, email)

    async def dispatch_email(self, email: OutboundEmail) -> None:
        await self._dispatch_email(email)

    def _serialize_email(self, email: OutboundEmail) -> dict[str, Any]:
        return {
            'to_addresses': list(email.to_addresses),
            'subject': email.subject,
            'body_plain': email.body_plain,
            'body_html': email.body_html,
            'in_reply_to': email.in_reply_to,
            'references': list(email.references or []),
            'reply_to': list(email.reply_to or []),
            'attachments': [
                {
                    'filename': item.filename,
                    'content_type': item.content_type,
                    'payload': base64.b64encode(item.payload).decode('ascii'),
                }
                for item in (email.attachments or [])
            ],
        }

    async def _apply_task(self, task, payload: Any, timeout: int = 180) -> Any:
        loop = asyncio.get_running_loop()

        def _invoke():
            result = task.apply_async(args=[payload])
            return result.get(timeout=timeout)

        return await loop.run_in_executor(None, _invoke)

    async def _build_llm_messages(self, conversation: Conversation) -> list[dict[str, str]]:
        system_message = {
            "role": "system",
            "content": self._system_prompt(conversation.language),
        }
        historical_messages: list[dict[str, str]] = [system_message]

        scenario_state = conversation.__dict__.get("scenario_state")
        if scenario_state and getattr(scenario_state, "scenario", None):
            scenario = scenario_state.scenario
            pieces: list[str] = []
            if scenario.subject:
                pieces.append(f"Scenario subject: {scenario.subject}")
            if scenario.description:
                pieces.append(scenario.description)
            if scenario.ai_preamble:
                pieces.append(scenario.ai_preamble)
            active_step = scenario_state.active_step
            if active_step:
                title = active_step.title or f"Step {active_step.order_index}"
                pieces.append(f"Active step: {title}")
                if active_step.description:
                    pieces.append(active_step.description)
                if active_step.ai_instructions:
                    pieces.append(f"Instructions: {active_step.ai_instructions}")
            if pieces:
                historical_messages.append({"role": "system", "content": "\n".join(pieces)})

        if "messages" in conversation.__dict__:
            recent_messages = list(conversation.messages)[-6:]
        else:
            stmt = (
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.created_at.asc())
            )
            recent_messages = (await self.session.scalars(stmt)).all()[-6:]

        for message in recent_messages:
            content = message.body_plain or self._html_to_text(message.body_html)
            if not content:
                continue
            role = "assistant" if message.sender_type != MessageSender.CLIENT else "user"
            historical_messages.append({"role": role, "content": content})
        return historical_messages

    def _system_prompt(self, language: str | None) -> str:
        base_prompt = (
            "You are a virtual sales assistant. Reply politely, professionally, and concisely. "
            "Use the assigned scenario and the conversation history as context. If a human manager is required, start the reply with the word 'MANAGER' and explain why."
        )
        if language and language.startswith("ru"):
            base_prompt = (
                "You are a virtual sales assistant. Reply in Russian, politely and to the point. "
                "Use the assigned scenario and the conversation history as context. If a human manager is required, start the reply with the word 'MANAGER' and explain why."
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
        return "<p>" + escaped.replace("\n\n", "</p><p>").replace("\n", "<br />") + "</p>"

    @staticmethod
    def _html_to_text(html: str | None) -> str | None:
        if not html:
            return None
        import re

        text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        return text



















