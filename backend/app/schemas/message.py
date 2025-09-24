from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.models.enums import MessageDirection, MessageSender
from app.schemas.common import ORMModel


class MessageRead(ORMModel):
    id: int
    sender_type: MessageSender
    direction: MessageDirection
    subject: str | None = None
    body_plain: str | None = None
    body_html: str | None = None
    detected_language: str | None = None
    sent_at: datetime | None = None
    received_at: datetime | None = None
    requires_attention: bool = False
    is_draft: bool = False


class MessageSendRequest(ORMModel):
    text: str
    send_mode: str = Field(pattern=r"^(approve_ai|manual)$")
    subject: str | None = None
