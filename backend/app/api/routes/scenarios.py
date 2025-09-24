from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas import (
    ScenarioCreate,
    ScenarioRead,
    ScenarioStepCreate,
    ScenarioStepPatch,
    ScenarioStepRead,
)
from app.services.auth_service import ensure_superuser, get_current_active_user
from app.services.scenario_service import ScenarioService

from ..deps import get_scenario_service

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("/", response_model=List[ScenarioRead])
async def list_scenarios(
    service: ScenarioService = Depends(get_scenario_service),
    _user=Depends(get_current_active_user),
) -> List[ScenarioRead]:
    scenarios = await service.list_scenarios()
    return [ScenarioRead.model_validate(scenario) for scenario in scenarios]


@router.post("/", response_model=ScenarioRead, status_code=status.HTTP_201_CREATED)
async def create_scenario(
    payload: ScenarioCreate,
    service: ScenarioService = Depends(get_scenario_service),
    _superuser=Depends(ensure_superuser),
) -> ScenarioRead:
    scenario = await service.create_scenario(payload)
    await service.session.commit()
    return ScenarioRead.model_validate(scenario)


@router.post("/{scenario_id}/steps", response_model=ScenarioStepRead, status_code=status.HTTP_201_CREATED)
async def add_step(
    scenario_id: int,
    payload: ScenarioStepCreate,
    service: ScenarioService = Depends(get_scenario_service),
    _superuser=Depends(ensure_superuser),
) -> ScenarioStepRead:
    scenario = await service.get_scenario(scenario_id)
    step = await service.add_step(scenario, payload)
    await service.session.commit()
    return ScenarioStepRead.model_validate(step)


@router.patch("/{scenario_id}/steps/{step_id}", response_model=ScenarioStepRead)
async def update_step(
    scenario_id: int,
    step_id: int,
    payload: ScenarioStepPatch,
    service: ScenarioService = Depends(get_scenario_service),
    _superuser=Depends(ensure_superuser),
) -> ScenarioStepRead:
    scenario = await service.get_scenario(scenario_id)
    step = next((item for item in scenario.steps if item.id == step_id), None)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario step not found")
    await service.update_step(step, payload)
    await service.session.commit()
    return ScenarioStepRead.model_validate(step)
