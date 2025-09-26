from __future__ import annotations

from datetime import datetime
from typing import List, TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import ConversationStatus

if TYPE_CHECKING:
    from app.models.attachment import MessageAttachment
    from app.models.log import ConversationLogEntry
    from app.models.scenario import ConversationScenarioState


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"))
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, name="conversation_status"),
        default=ConversationStatus.AWAITING_RESPONSE,
    )
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_message_preview: Mapped[str | None] = mapped_column(String(500), nullable=True)

    client: Mapped["Client"] = relationship(back_populates="conversations")
    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.sent_at",
    )
    scenario_state: Mapped["ConversationScenarioState | None"] = relationship(
        back_populates="conversation",
        uselist=False,
        cascade="all, delete-orphan",
    )
    logs: Mapped[List["ConversationLogEntry"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationLogEntry.created_at",
    )
    attachments: Mapped[List["MessageAttachment"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="MessageAttachment.created_at",
    )

    def mark_updated(self, message_time: datetime) -> None:
        self.last_message_at = message_time
