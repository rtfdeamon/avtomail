"""Add scenarios and conversation logs

Revision ID: 20240917_02
Revises: 20240917_01
Create Date: 2025-09-17 14:40:00

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20240917_02"
down_revision = "20240917_01"
branch_labels = None
depends_on = None


conversation_log_event = sa.Enum(
    "automation_triggered",
    "llm_draft_created",
    "human_intervention_required",
    "message_sent",
    "scenario_step_changed",
    "scenario_assigned",
    "note",
    name="conversation_log_event",
)

conversation_log_actor = sa.Enum(
    "system",
    "assistant",
    "manager",
    "client",
    name="conversation_log_actor",
)


def upgrade() -> None:
    bind = op.get_bind()
    conversation_log_event.create(bind, checkfirst=True)
    conversation_log_actor.create(bind, checkfirst=True)

    op.create_table(
        "scenarios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ai_preamble", sa.Text(), nullable=True),
        sa.Column("operator_guidelines", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "scenario_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ai_instructions", sa.Text(), nullable=True),
        sa.Column("operator_hint", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scenario_steps_scenario_id", "scenario_steps", ["scenario_id"])

    op.create_table(
        "conversation_scenario_states",
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("scenario_id", sa.Integer(), sa.ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("active_step_id", sa.Integer(), sa.ForeignKey("scenario_steps.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "conversation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", conversation_log_event, nullable=False),
        sa.Column("actor", conversation_log_actor, nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conversation_logs_conversation_id", "conversation_logs", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_conversation_logs_conversation_id", table_name="conversation_logs")
    op.drop_table("conversation_logs")

    op.drop_table("conversation_scenario_states")

    op.drop_index("ix_scenario_steps_scenario_id", table_name="scenario_steps")
    op.drop_table("scenario_steps")
    op.drop_table("scenarios")

    bind = op.get_bind()
    conversation_log_event.drop(bind, checkfirst=True)
    conversation_log_actor.drop(bind, checkfirst=True)
