from __future__ import annotations

from app.schemas.common import ORMModel


class ClientSummary(ORMModel):
    id: int
    email: str
    name: str | None = None
    company: str | None = None
    locale: str | None = None


class ClientCreate(ORMModel):
    email: str
    name: str | None = None
    company: str | None = None
    locale: str | None = None
    timezone: str | None = None
