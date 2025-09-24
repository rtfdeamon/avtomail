from __future__ import annotations

from typing import Sequence

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.scenario import Scenario, ScenarioStep
from app.schemas.scenario import ScenarioCreate, ScenarioStepCreate, ScenarioStepPatch


class ScenarioService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _scenario_options(self):
        return (
            joinedload(Scenario.steps),
        )

    async def list_scenarios(self) -> Sequence[Scenario]:
        stmt: Select[Scenario] = select(Scenario).options(*self._scenario_options()).order_by(Scenario.name)
        return (await self.session.scalars(stmt)).unique().all()

    async def get_scenario(self, scenario_id: int) -> Scenario:
        stmt: Select[Scenario] = (
            select(Scenario)
            .options(*self._scenario_options())
            .where(Scenario.id == scenario_id)
        )
        return (await self.session.scalars(stmt)).unique().one()

    async def create_scenario(self, data: ScenarioCreate) -> Scenario:
        scenario = Scenario(
            name=data.name,
            subject=data.subject,
            description=data.description,
            ai_preamble=data.ai_preamble,
            operator_guidelines=data.operator_guidelines,
        )
        self.session.add(scenario)
        await self.session.flush()
        if data.steps:
            for step in data.steps:
                await self.add_step(scenario, step)
        return scenario

    async def add_step(self, scenario: Scenario, data: ScenarioStepCreate) -> ScenarioStep:
        step = ScenarioStep(
            scenario=scenario,
            order_index=data.order_index,
            title=data.title,
            description=data.description,
            ai_instructions=data.ai_instructions,
            operator_hint=data.operator_hint,
        )
        self.session.add(step)
        await self.session.flush()
        return step

    async def update_step(self, step: ScenarioStep, data: ScenarioStepPatch) -> ScenarioStep:
        if data.title is not None:
            step.title = data.title
        if data.description is not None:
            step.description = data.description
        if data.ai_instructions is not None:
            step.ai_instructions = data.ai_instructions
        if data.operator_hint is not None:
            step.operator_hint = data.operator_hint
        if data.order_index is not None:
            step.order_index = data.order_index
        await self.session.flush()
        return step

