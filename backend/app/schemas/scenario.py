from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel

from app.schemas.common import ORMModel


class ScenarioStepBase(BaseModel):
    order_index: int
    title: str | None = None
    description: str | None = None
    ai_instructions: str | None = None
    operator_hint: str | None = None


class ScenarioStepCreate(ScenarioStepBase):
    pass


class ScenarioStepRead(ORMModel):
    id: int
    order_index: int
    title: str | None = None
    description: str | None = None
    ai_instructions: str | None = None
    operator_hint: str | None = None


class ScenarioBase(BaseModel):
    name: str
    subject: str | None = None
    description: str | None = None
    ai_preamble: str | None = None
    operator_guidelines: str | None = None


class ScenarioCreate(ScenarioBase):
    steps: List[ScenarioStepCreate] | None = None


class ScenarioUpdate(ScenarioBase):
    pass


class ScenarioRead(ORMModel):
    id: int
    name: str
    subject: str | None = None
    description: str | None = None
    ai_preamble: str | None = None
    operator_guidelines: str | None = None
    steps: List[ScenarioStepRead] = []


class ScenarioSummary(ORMModel):
    id: int
    name: str
    subject: str | None = None


class ScenarioStateSummary(ORMModel):
    scenario: ScenarioSummary
    active_step_id: int | None = None
    active_step_title: str | None = None


class ScenarioStateRead(ORMModel):
    scenario: ScenarioRead
    active_step: ScenarioStepRead | None = None
    next_step: ScenarioStepRead | None = None
    notes: str | None = None


class ScenarioAssignRequest(BaseModel):
    scenario_id: int
    starting_step_id: int | None = None
    notes: str | None = None


class ScenarioAdvanceRequest(BaseModel):
    step_id: int | None = None
    direction: str | None = None
    notes: str | None = None


class ScenarioStepPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    ai_instructions: str | None = None
    operator_hint: str | None = None
    order_index: int | None = None
