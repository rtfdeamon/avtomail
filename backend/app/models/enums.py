from __future__ import annotations

from enum import Enum


class ConversationStatus(str, Enum):
    AWAITING_RESPONSE = "awaiting_response"
    ANSWERED_BY_LLM = "answered_by_llm"
    NEEDS_HUMAN = "needs_human"
    CLOSED = "closed"


class MessageSender(str, Enum):
    CLIENT = "client"
    ASSISTANT = "assistant"
    ASSISTANT_DRAFT = "assistant_draft"
    MANAGER = "manager"


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    DRAFT = "draft"
