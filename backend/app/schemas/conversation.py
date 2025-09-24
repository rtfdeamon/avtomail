from __future__ import annotations

from datetime import datetime
from typing import List

from app.models.enums import ConversationStatus
from app.schemas.client import ClientSummary
from app.schemas.common import ORMModel
from app.schemas.message import MessageRead


class ConversationSummary(ORMModel):
    id: int
    client: ClientSummary
    topic: str | None = None
    status: ConversationStatus
    last_message_at: datetime | None = None
    unread_count: int = 0


class ConversationDetail(ORMModel):
    id: int
    client: ClientSummary
    topic: str | None = None
    status: ConversationStatus
    messages: List[MessageRead]

