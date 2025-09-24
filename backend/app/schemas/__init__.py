from __future__ import annotations

from app.schemas.client import ClientCreate, ClientSummary
from app.schemas.conversation import ConversationDetail, ConversationSummary
from app.schemas.message import MessageRead, MessageSendRequest

__all__ = [
    "ClientCreate",
    "ClientSummary",
    "ConversationDetail",
    "ConversationSummary",
    "MessageRead",
    "MessageSendRequest",
]
