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

class ConversationLogEvent(str, Enum):
    AUTOMATION_TRIGGERED = "automation_triggered"
    LLM_DRAFT_CREATED = "llm_draft_created"
    HUMAN_INTERVENTION_REQUIRED = "human_intervention_required"
    MESSAGE_SENT = "message_sent"
    SCENARIO_STEP_CHANGED = "scenario_step_changed"
    SCENARIO_ASSIGNED = "scenario_assigned"
    NOTE = "note"

class ConversationActor(str, Enum):
    SYSTEM = "system"
    ASSISTANT = "assistant"
    MANAGER = "manager"
    CLIENT = "client"
