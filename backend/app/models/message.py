from __future__ import annotations

from datetime import datetime
from typing import List, TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import MessageDirection, MessageSender

if TYPE_CHECKING:
    from app.models.attachment import MessageAttachment


class Message(TimestampMixin, Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_type: Mapped[MessageSender] = mapped_column(
        Enum(MessageSender, name="message_sender"),
        default=MessageSender.CLIENT,
    )
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection, name="message_direction"),
        default=MessageDirection.INBOUND,
    )
    sender_address: Mapped[str | None] = mapped_column(String(320), nullable=True)
    sender_display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body_plain: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(nullable=True)
    requires_attention: Mapped[bool] = mapped_column(default=False)
    is_draft: Mapped[bool] = mapped_column(default=False)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    attachments: Mapped[List["MessageAttachment"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
    )
