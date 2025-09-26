"""Add message attachments table and bootstrap admin user

Revision ID: 20240925_03
Revises: 20240917_02
Create Date: 2025-09-25 10:00:00

"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from passlib.context import CryptContext


revision = "20240925_03"
down_revision = "20240917_02"
branch_labels = None
depends_on = None


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def upgrade() -> None:
    op.create_table(
        "message_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("is_inline", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_inbound", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_message_attachments_conversation_id",
        "message_attachments",
        ["conversation_id"],
    )
    op.create_index(
        "ix_message_attachments_message_id",
        "message_attachments",
        ["message_id"],
    )

    _ensure_default_admin()


def downgrade() -> None:
    op.drop_index("ix_message_attachments_message_id", table_name="message_attachments")
    op.drop_index("ix_message_attachments_conversation_id", table_name="message_attachments")
    op.drop_table("message_attachments")


def _ensure_default_admin() -> None:
    email = (os.getenv("DEFAULT_ADMIN_EMAIL") or "admin").strip().lower()
    password = os.getenv("DEFAULT_ADMIN_PASSWORD") or "admin"
    if not email or not password:
        return

    bind = op.get_bind()
    existing = bind.execute(
        sa.text("SELECT id, is_superuser FROM users WHERE email = :email"),
        {"email": email},
    ).mappings().first()

    if existing:
        if not existing["is_superuser"]:
            bind.execute(
                sa.text("UPDATE users SET is_superuser = :flag WHERE id = :user_id"),
                {"flag": True, "user_id": existing["id"]},
            )
        return

    now = datetime.now(timezone.utc)
    hashed = pwd_context.hash(password)
    bind.execute(
        sa.text(
            """
            INSERT INTO users (email, hashed_password, full_name, is_active, is_superuser, created_at, updated_at)
            VALUES (:email, :hashed_password, :full_name, :is_active, :is_superuser, :created_at, :updated_at)
            """
        ),
        {
            "email": email,
            "hashed_password": hashed,
            "full_name": "Administrator",
            "is_active": True,
            "is_superuser": True,
            "created_at": now,
            "updated_at": now,
        },
    )
