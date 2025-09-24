"""Initial database schema

Revision ID: 20240917_01
Revises: None
Create Date: 2025-09-17 11:16:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20240917_01"
down_revision = None
branch_labels = None
depends_on = None


conversation_status = sa.Enum(
    "awaiting_response",
    "answered_by_llm",
    "needs_human",
    "closed",
    name="conversation_status",
)

message_sender = sa.Enum(
    "client",
    "assistant",
    "assistant_draft",
    "manager",
    name="message_sender",
)

message_direction = sa.Enum(
    "inbound",
    "outbound",
    "draft",
    name="message_direction",
)


def upgrade() -> None:
    bind = op.get_bind()
    conversation_status.create(bind, checkfirst=True)
    message_sender.create(bind, checkfirst=True)
    message_direction.create(bind, checkfirst=True)

    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("locale", sa.String(length=10), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_clients_email", "clients", ["email"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=True),
        sa.Column("status", conversation_status, nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
        sa.Column("last_message_preview", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("in_reply_to", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("sender_type", message_sender, nullable=False),
        sa.Column("direction", message_direction, nullable=False),
        sa.Column("sender_address", sa.String(length=320), nullable=True),
        sa.Column("sender_display_name", sa.String(length=255), nullable=True),
        sa.Column("body_plain", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("detected_language", sa.String(length=16), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("requires_attention", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_draft", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_external_id", "messages", ["external_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_messages_external_id", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")

    op.drop_table("conversations")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    op.drop_index("ix_clients_email", table_name="clients")
    op.drop_table("clients")

    message_direction.drop(op.get_bind(), checkfirst=True)
    message_sender.drop(op.get_bind(), checkfirst=True)
    conversation_status.drop(op.get_bind(), checkfirst=True)
