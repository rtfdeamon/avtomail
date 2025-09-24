from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models.enums import ConversationActor, ConversationLogEvent
from app.schemas.common import ORMModel


class ConversationLogEntryRead(ORMModel):
    id: int
    event_type: ConversationLogEvent
    actor: ConversationActor
    summary: str
    details: dict[str, Any] | None = None
    context: str | None = None
    created_at: datetime


class ConversationNoteCreate(BaseModel):
    summary: str
    context: str | None = None
    details: dict[str, Any] | None = None
