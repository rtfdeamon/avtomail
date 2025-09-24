from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import auth, conversations, scenarios

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(conversations.router)
api_router.include_router(scenarios.router)
