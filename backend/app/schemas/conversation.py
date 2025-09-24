from __future__ import annotations

from datetime import datetime
from typing import List

from app.models.enums import ConversationStatus
from app.schemas.client import ClientSummary
from app.schemas.common import ORMModel
from app.schemas.log import ConversationLogEntryRead
from app.schemas.message import MessageRead
from app.schemas.scenario import ScenarioStateRead, ScenarioStateSummary


class ConversationSummary(ORMModel):
    id: int
    client: ClientSummary
    topic: str | None = None
    status: ConversationStatus
    last_message_at: datetime | None = None
    unread_count: int = 0
    scenario: ScenarioStateSummary | None = None


class ConversationDetail(ORMModel):
    id: int
    client: ClientSummary
    topic: str | None = None
    status: ConversationStatus
    messages: List[MessageRead]
    scenario_state: ScenarioStateRead | None = None
    logs: List[ConversationLogEntryRead] = []
