from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.services.conversation_service import ConversationService
from app.services.scenario_service import ScenarioService


async def get_settings_dependency() -> Settings:
    return get_settings()


async def get_conversation_service(
    session: AsyncSession = Depends(get_db),
) -> ConversationService:
    return ConversationService(session)


async def get_scenario_service(
    session: AsyncSession = Depends(get_db),
) -> ScenarioService:
    return ScenarioService(session)
