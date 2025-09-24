from __future__ import annotations

import asyncio

from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.logging import logger
from app.db.session import AsyncSessionLocal
from app.services.automation_service import AutomationService
from app.services.mail_service import MailService, MailServiceConnectionError


class InboxPoller:
    """Background worker that periodically pulls inbound emails and processes them."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.mail_service = MailService(self.settings)
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    @property
    def is_enabled(self) -> bool:
        return bool(self.settings.imap_username and self.settings.imap_password)

    def start(self) -> None:
        if not self.is_enabled:
            logger.warning("Inbox poller disabled: IMAP credentials missing")
            return
        if self._task and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Inbox poller started")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await self._task
            logger.info("Inbox poller stopped")

    async def _run_loop(self) -> None:
        interval = max(30, self.settings.poll_interval_seconds)
        while not self._stop_event.is_set():
            try:
                await self.poll_once()
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Inbox poller iteration failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue

    async def poll_once(self) -> None:
        try:
            emails = self.mail_service.fetch_unseen()
        except MailServiceConnectionError as exc:
            logger.warning("Skipping IMAP fetch: %s", exc)
            return
        if not emails:
            return
        logger.info("Fetched %s new email(s) from IMAP", len(emails))
        for email in emails:
            async with AsyncSessionLocal() as session:
                service = AutomationService(
                    session,
                    settings=self.settings,
                    mail_service=self.mail_service,
                )
                try:
                    result = await service.process_inbound(email)
                except Exception as exc:  # pragma: no cover - unexpected failure
                    logger.exception("Failed to process inbound email %s: %s", email.message_id, exc)
                    continue
                if not result.requires_human:
                    try:
                        self.mail_service.move_to_processed(email.imap_uid)
                    except MailServiceConnectionError as exc:
                        logger.warning("Could not move email %s to processed folder: %s", email.message_id, exc)
                    except Exception as exc:  # pragma: no cover - best effort
                        logger.warning(
                            "Could not move email %s to processed folder: %s",
                            email.message_id,
                            exc,
                        )


def register_inbox_poller(app: FastAPI, poller: InboxPoller) -> None:
    app.state.inbox_poller = poller


async def start_poller(app: FastAPI) -> None:
    poller: InboxPoller = app.state.inbox_poller
    poller.start()


async def stop_poller(app: FastAPI) -> None:
    poller: InboxPoller = app.state.inbox_poller
    await poller.stop()
