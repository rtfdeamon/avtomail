from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Scenario(TimestampMixin, Base):
    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_preamble: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_guidelines: Mapped[str | None] = mapped_column(Text, nullable=True)

    steps: Mapped[list["ScenarioStep"]] = relationship(
        back_populates="scenario",
        cascade="all, delete-orphan",
        order_by="ScenarioStep.order_index",
    )
    states: Mapped[list["ConversationScenarioState"]] = relationship(
        back_populates="scenario",
        cascade="all, delete-orphan",
    )


class ScenarioStep(TimestampMixin, Base):
    __tablename__ = "scenario_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_hint: Mapped[str | None] = mapped_column(Text, nullable=True)

    scenario: Mapped[Scenario] = relationship(back_populates="steps")


class ConversationScenarioState(TimestampMixin, Base):
    __tablename__ = "conversation_scenario_states"

    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)
    active_step_id: Mapped[int | None] = mapped_column(ForeignKey("scenario_steps.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    scenario: Mapped[Scenario] = relationship(back_populates="states")
    active_step: Mapped[ScenarioStep | None] = relationship(foreign_keys=[active_step_id])
    conversation: Mapped["Conversation"] = relationship(back_populates="scenario_state")
