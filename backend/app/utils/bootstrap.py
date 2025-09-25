from __future__ import annotations

from sqlalchemy import select

from app.core.config import Settings
from app.core.logging import logger
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.services.auth_service import AuthService


async def ensure_default_admin(settings: Settings) -> None:
    """Create default admin user if it does not yet exist."""

    async with AsyncSessionLocal() as session:
        service = AuthService(settings, session)
        stmt = select(User).where(User.email == settings.default_admin_email.lower())
        existing = await session.scalar(stmt)
        if existing:
            if not existing.is_superuser:
                existing.is_superuser = True
                await session.commit()
                logger.info("Default admin %s ensured (existing user elevated)", settings.default_admin_email)
            return
        hashed = service.hash_password(settings.default_admin_password)
        user = User(
            email=settings.default_admin_email.lower(),
            hashed_password=hashed,
            full_name="Administrator",
            is_active=True,
            is_superuser=True,
        )
        session.add(user)
        await session.commit()
        logger.info("Default admin %s created", settings.default_admin_email)
