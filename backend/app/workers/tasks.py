from __future__ import annotations

import asyncio
import base64
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger

from app.core.config import get_settings
from app.services.llm_service import LLMRequest, LLMResponse, LLMService
from app.services.mail_service import MailService, OutboundAttachment, OutboundEmail

logger = get_task_logger(__name__)


@shared_task(name="llm.generate_reply")
def generate_llm_reply_task(payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    service = LLMService(settings)
    request = LLMRequest(
        messages=payload.get("messages", []),
        temperature=payload.get("temperature", 0.2),
        max_tokens=payload.get("max_tokens"),
    )

    async def _run() -> LLMResponse:
        response = await service.generate_reply(request)
        await service.aclose()
        return response

    response = asyncio.run(_run())
    logger.debug("LLM reply generated via worker (requires_human=%s)", response.requires_human)
    return {
        "content": response.content,
        "requires_human": response.requires_human,
        "raw": response.raw,
    }


@shared_task(name="mail.send_email")
def send_email_task(payload: dict[str, Any]) -> None:
    settings = get_settings()
    service = MailService(settings)
    attachments_payload = payload.get("attachments") or []
    attachments = [
        OutboundAttachment(
            filename=item.get("filename", "attachment"),
            content_type=item.get("content_type"),
            payload=base64.b64decode(item.get("payload", "")),
        )
        for item in attachments_payload
    ]
    email = OutboundEmail(
        to_addresses=payload["to_addresses"],
        subject=payload["subject"],
        body_plain=payload["body_plain"],
        body_html=payload.get("body_html"),
        in_reply_to=payload.get("in_reply_to"),
        references=payload.get("references") or [],
        reply_to=payload.get("reply_to"),
        attachments=attachments or None,
    )
    service.send_email(email)
    logger.debug("Email dispatched to %s", ", ".join(email.to_addresses))
