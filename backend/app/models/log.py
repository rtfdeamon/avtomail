from __future__ import annotations

from sqlalchemy import Enum, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import ConversationActor, ConversationLogEvent


class ConversationLogEntry(TimestampMixin, Base):
    __tablename__ = "conversation_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[ConversationLogEvent] = mapped_column(Enum(ConversationLogEvent, name="conversation_log_event"))
    actor: Mapped[ConversationActor] = mapped_column(Enum(ConversationActor, name="conversation_log_actor"))
    summary: Mapped[str] = mapped_column(String(500))
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)

    conversation: Mapped["Conversation"] = relationship(back_populates="logs")
