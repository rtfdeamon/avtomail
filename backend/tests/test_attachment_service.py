from __future__ import annotations

import io

import pytest
from starlette.datastructures import UploadFile

from app.core.config import Settings
from app.services.attachment_service import AttachmentService, AttachmentTooLargeError


@pytest.mark.asyncio
async def test_save_upload_stores_file(tmp_path):
    settings = Settings(attachments_dir=str(tmp_path / "attachments"), max_attachment_size_mb=1, enable_task_queue=False)
    service = AttachmentService(settings)
    upload = UploadFile(filename="brief.txt", file=io.BytesIO(b"test"))

    storage_path, size = await service.save_upload(conversation_id=1, upload=upload)

    assert size == 4
    stored_file = (tmp_path / "attachments" / storage_path)
    assert stored_file.exists()
    assert stored_file.read_bytes() == b"test"


@pytest.mark.asyncio
async def test_save_bytes_respects_limit(tmp_path):
    settings = Settings(attachments_dir=str(tmp_path / "attachments"), enable_task_queue=False)
    service = AttachmentService(settings)
    service.max_bytes = 1

    with pytest.raises(AttachmentTooLargeError):
        await service.save_bytes(conversation_id=1, filename="large.bin", payload=b"too big")
