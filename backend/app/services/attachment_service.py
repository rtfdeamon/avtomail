from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

import aiofiles
from fastapi import UploadFile

from app.core.config import Settings, get_settings
from app.core.logging import logger


class AttachmentTooLargeError(ValueError):
    """Raised when an attachment exceeds the configured size limit."""


class AttachmentService:
    """Persist attachments to disk and enforce size constraints."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_path = Path(self.settings.attachments_dir).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        raw_limit = float(self.settings.max_attachment_size_mb) * 1024 * 1024
        if raw_limit <= 0:
            self.max_bytes = 0
        else:
            self.max_bytes = max(int(raw_limit), 1)

    async def save_upload(self, conversation_id: int, upload: UploadFile) -> Tuple[str, int]:
        filename = self._sanitize_filename(upload.filename)
        storage_path, absolute_path = self._build_destination(conversation_id, filename)
        size = 0
        try:
            async with aiofiles.open(absolute_path, "wb") as buffer:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    self._enforce_size(size)
                    await buffer.write(chunk)
        except AttachmentTooLargeError:
            await upload.seek(0)
            if absolute_path.exists():
                absolute_path.unlink(missing_ok=True)
            raise
        await upload.seek(0)
        logger.debug("Stored upload %s for conversation %s (%s bytes)", filename, conversation_id, size)
        return storage_path, size

    async def save_bytes(self, conversation_id: int, filename: str, payload: bytes) -> Tuple[str, int]:
        size = len(payload)
        self._enforce_size(size)
        storage_path, absolute_path = self._build_destination(conversation_id, filename)
        async with aiofiles.open(absolute_path, "wb") as buffer:
            await buffer.write(payload)
        logger.debug("Stored attachment bytes %s for conversation %s (%s bytes)", filename, conversation_id, size)
        return storage_path, size

    def resolve_path(self, storage_path: str) -> Path:
        candidate = (self.base_path / storage_path).resolve()
        try:
            candidate.relative_to(self.base_path)
        except ValueError as exc:  # pragma: no cover - defensive
            raise FileNotFoundError(storage_path) from exc
        return candidate

    async def read_bytes(self, storage_path: str) -> bytes:
        absolute = self.resolve_path(storage_path)
        async with aiofiles.open(absolute, "rb") as buffer:
            return await buffer.read()

    def _build_destination(self, conversation_id: int, filename: str) -> Tuple[str, Path]:
        safe_filename = self._sanitize_filename(filename)
        suffix = Path(safe_filename).suffix
        unique_name = f"{os.urandom(16).hex()}{suffix}"
        relative_dir = Path(str(conversation_id))
        target_dir = self.base_path / relative_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        relative_path = (relative_dir / unique_name).as_posix()
        absolute_path = target_dir / unique_name
        return relative_path, absolute_path

    def _sanitize_filename(self, filename: str | None) -> str:
        if not filename:
            return "attachment"
        name = Path(filename).name.strip()
        return name or "attachment"

    def _enforce_size(self, size: int) -> None:
        if self.max_bytes and size > self.max_bytes:
            raise AttachmentTooLargeError(
                f"Attachment size {size} exceeds limit {self.max_bytes} bytes",
            )


__all__ = ["AttachmentService", "AttachmentTooLargeError"]
