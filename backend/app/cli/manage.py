from __future__ import annotations

import asyncio
from typing import Optional

import typer
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.services.auth_service import AuthService

app = typer.Typer(help="Management commands for Avtomail backend")


async def _create_or_update_user(
    email: str,
    password: str,
    full_name: str | None,
    is_superuser: bool,
    ensure_exists: bool,
) -> None:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        service = AuthService(settings, session)
        stmt = select(User).where(User.email == email.lower())
        user = await session.scalar(stmt)
        if user:
            if ensure_exists:
                typer.echo(f"User {email} already exists; nothing to do.")
                return
            user.hashed_password = service.hash_password(password)
            user.full_name = full_name or user.full_name
            user.is_superuser = is_superuser
            user.is_active = True
            typer.echo(f"Updated user {email} (superuser={is_superuser}).")
        else:
            hashed = service.hash_password(password)
            user = User(
                email=email.lower(),
                hashed_password=hashed,
                full_name=full_name,
                is_superuser=is_superuser,
                is_active=True,
            )
            session.add(user)
            typer.echo(f"Created user {email} (superuser={is_superuser}).")
        await session.commit()


@app.command("create-user")
def create_user(
    email: str = typer.Argument(..., help="Email address"),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
    full_name: Optional[str] = typer.Option(None, help="Full name"),
    superuser: bool = typer.Option(False, help="Grant superuser privileges"),
) -> None:
    """Create a new user or update existing credentials."""

    asyncio.run(_create_or_update_user(email, password, full_name, superuser, ensure_exists=False))


@app.command("ensure-admin")
def ensure_admin(
    email: str = typer.Argument(..., help="Admin email"),
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
    full_name: Optional[str] = typer.Option("Administrator", help="Full name"),
) -> None:
    """Create a superuser if it does not yet exist."""

    asyncio.run(_create_or_update_user(email, password, full_name, True, ensure_exists=True))


if __name__ == "__main__":
    app()
