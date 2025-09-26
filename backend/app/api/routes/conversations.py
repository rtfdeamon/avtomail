from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import NoResultFound

from app.models.attachment import MessageAttachment
from app.models.enums import ConversationActor, ConversationLogEvent, MessageDirection, MessageSender
from app.models.scenario import ConversationScenarioState, ScenarioStep
from app.schemas import (
    ConversationDetail,
    ConversationLogEntryRead,
    ConversationNoteCreate,
    ConversationSummary,
    MessageAttachmentRead,
    MessageRead,
    MessageSendRequest,
    ScenarioAdvanceRequest,
    ScenarioAssignRequest,
    ScenarioRead,
    ScenarioStateRead,
    ScenarioStateSummary,
    ScenarioStepRead,
    ScenarioSummary,
)
from app.services.attachment_service import AttachmentService, AttachmentTooLargeError
from app.services.automation_service import AutomationService
from app.services.auth_service import ensure_superuser, get_current_active_user
from app.services.conversation_service import ConversationService
from app.services.mail_service import OutboundAttachment, OutboundEmail
from app.services.scenario_service import ScenarioService

from ..deps import (
    get_attachment_service,
    get_conversation_service,
    get_scenario_service,
    get_settings_dependency,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _build_step_title(step: ScenarioStep) -> str:
    return step.title or f"Step {step.order_index}"


def _next_step(state: ConversationScenarioState | None) -> ScenarioStep | None:
    if not state or not state.scenario or not state.scenario.steps:
        return None
    steps = sorted(state.scenario.steps, key=lambda item: item.order_index)
    if state.active_step is None:
        return steps[0]
    for index, step in enumerate(steps):
        if step.id == state.active_step.id and index + 1 < len(steps):
            return steps[index + 1]
    return None


def _attachment_to_schema(
    request: Request,
    conversation_id: int,
    message_id: int,
    attachment: MessageAttachment,
) -> MessageAttachmentRead:
    download_url = request.url_for(
        'download_conversation_attachment',
        conversation_id=conversation_id,
        message_id=message_id,
        attachment_id=attachment.id,
    )
    return MessageAttachmentRead(
        id=attachment.id,
        filename=attachment.filename,
        content_type=attachment.content_type,
        file_size=attachment.file_size,
        is_inline=attachment.is_inline,
        is_inbound=attachment.is_inbound,
        download_url=str(download_url),
    )

def _scenario_state_summary(state: ConversationScenarioState | None) -> ScenarioStateSummary | None:
    if state is None or state.scenario is None:
        return None
    active = state.active_step
    return ScenarioStateSummary(
        scenario=ScenarioSummary.model_validate(state.scenario),
        active_step_id=active.id if active else None,
        active_step_title=_build_step_title(active) if active else None,
    )


def _scenario_state_read(
    state: ConversationScenarioState | None,
    *,
    include_steps: bool = False,
) -> ScenarioStateRead | None:
    if state is None or state.scenario is None:
        return None
    scenario_model = ScenarioRead.model_validate(state.scenario)
    if include_steps:
        scenario_model.steps = sorted(
            [ScenarioStepRead.model_validate(step) for step in state.scenario.steps],
            key=lambda item: item.order_index,
        )
    else:
        scenario_model.steps = []
    active = ScenarioStepRead.model_validate(state.active_step) if state.active_step else None
    next_step = _next_step(state)
    return ScenarioStateRead(
        scenario=scenario_model,
        active_step=active,
        next_step=ScenarioStepRead.model_validate(next_step) if next_step else None,
        notes=state.notes,
    )


@router.get("/", response_model=List[ConversationSummary])
async def list_conversations(
    service: ConversationService = Depends(get_conversation_service),
    _user=Depends(get_current_active_user),
) -> List[ConversationSummary]:
    conversations = await service.list_conversations()
    unread_map = await service.unread_counts([conv.id for conv in conversations])
    summaries: List[ConversationSummary] = []
    for conv in conversations:
        summaries.append(
            ConversationSummary(
                id=conv.id,
                client=conv.client,
                topic=conv.topic,
                status=conv.status,
                last_message_at=conv.last_message_at,
                unread_count=unread_map.get(conv.id, 0),
                scenario=_scenario_state_summary(conv.scenario_state),
            )
        )
    return summaries


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int,
    request: Request,
    service: ConversationService = Depends(get_conversation_service),
    _user=Depends(get_current_active_user),
) -> ConversationDetail:
    try:
        conversation = await service.get_conversation(conversation_id)
    except NoResultFound as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    messages: List[MessageRead] = []
    for message in conversation.messages:
        attachment_models = [
            _attachment_to_schema(request, conversation.id, message.id, attachment)
            for attachment in getattr(message, "attachments", [])
        ]
        messages.append(
            MessageRead(
                id=message.id,
                sender_type=message.sender_type,
                direction=message.direction,
                subject=message.subject,
                body_plain=message.body_plain,
                body_html=message.body_html,
                detected_language=message.detected_language,
                sent_at=message.sent_at,
                received_at=message.received_at,
                requires_attention=message.requires_attention,
                is_draft=message.is_draft,
                attachments=attachment_models,
            )
        )
    logs = sorted(conversation.logs, key=lambda entry: entry.created_at)
    return ConversationDetail(
        id=conversation.id,
        client=conversation.client,
        topic=conversation.topic,
        status=conversation.status,
        messages=messages,
        scenario_state=_scenario_state_read(conversation.scenario_state, include_steps=True),
        logs=[ConversationLogEntryRead.model_validate(entry) for entry in logs],
    )


@router.post("/{conversation_id}/send", response_model=MessageRead)
async def send_message(
    conversation_id: int,
    request: Request,
    service: ConversationService = Depends(get_conversation_service),
    attachment_service: AttachmentService = Depends(get_attachment_service),
    settings: Settings = Depends(get_settings_dependency),
    _user=Depends(get_current_active_user),
) -> MessageRead:
    try:
        conversation = await service.get_conversation(conversation_id)
    except NoResultFound as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    content_type = request.headers.get('content-type', '')
    upload_files: list[UploadFile] = []
    if content_type.startswith('multipart/form-data'):
        form = await request.form()
        text = (form.get('text') or '').strip()
        send_mode = form.get('send_mode')
        subject = form.get('subject')
        upload_files = [
            item for item in form.getlist('attachments') if isinstance(item, UploadFile)
        ]
    else:
        try:
            payload_data = await request.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid payload') from exc
        text = (payload_data.get('text') or '').strip()
        send_mode = payload_data.get('send_mode')
        subject = payload_data.get('subject')

    try:
        payload = MessageSendRequest(text=text, send_mode=send_mode, subject=subject)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc

    if not payload.text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Message text is required')

    sender_type = MessageSender.ASSISTANT if payload.send_mode == 'approve_ai' else MessageSender.MANAGER

    message = await service.record_outbound_message(conversation, payload, sender_type)

    saved_attachments: list[MessageAttachment] = []
    for upload in upload_files:
        try:
            storage_path, size = await attachment_service.save_upload(conversation.id, upload)
        except AttachmentTooLargeError as exc:  # pragma: no cover - defensive
            await upload.close()
            await service.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=str(exc),
            ) from exc
        attachment = MessageAttachment(
            conversation_id=conversation.id,
            message=message,
            filename=upload.filename or 'attachment',
            content_type=upload.content_type,
            file_size=size,
            storage_path=storage_path,
            is_inline=False,
            is_inbound=False,
            uploaded_by_id=getattr(_user, 'id', None),
        )
        service.session.add(attachment)
        saved_attachments.append(attachment)
        await upload.close()

    await service.session.flush()

    outbound_attachments: list[OutboundAttachment] = []
    for attachment in saved_attachments:
        data = await attachment_service.read_bytes(attachment.storage_path)
        outbound_attachments.append(
            OutboundAttachment(
                filename=attachment.filename,
                content_type=attachment.content_type,
                payload=data,
            )
        )

    if not conversation.client or not conversation.client.email:
        await service.session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Client email is missing')

    last_inbound = next(
        (msg for msg in reversed(conversation.messages) if msg.direction == MessageDirection.INBOUND),
        None,
    )
    references: list[str] = []
    if last_inbound and last_inbound.external_id:
        references.append(last_inbound.external_id)
    if last_inbound and last_inbound.in_reply_to:
        references.append(last_inbound.in_reply_to)
    if references:
        references = list(dict.fromkeys(filter(None, references)))

    outbound_email = OutboundEmail(
        to_addresses=[conversation.client.email],
        subject=message.subject or payload.subject or (conversation.topic or ''),
        body_plain=payload.text,
        body_html=AutomationService._plain_to_html(payload.text),
        in_reply_to=last_inbound.external_id if last_inbound else None,
        references=references or None,
        attachments=outbound_attachments or None,
    )

    dispatcher = AutomationService(service.session, settings=settings)
    try:
        await dispatcher.dispatch_email(outbound_email)
    except Exception as exc:  # pragma: no cover - defensive
        await service.session.rollback()
        logger.exception('Failed to dispatch manual email for conversation %s: %s', conversation.id, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail='Failed to send email') from exc

    await service.session.commit()
    await service.session.refresh(message, attribute_names=['attachments'])

    attachment_models = [
        _attachment_to_schema(request, conversation.id, message.id, attachment)
        for attachment in getattr(message, 'attachments', [])
    ]
    return MessageRead(
        id=message.id,
        sender_type=message.sender_type,
        direction=message.direction,
        subject=message.subject,
        body_plain=message.body_plain,
        body_html=message.body_html,
        detected_language=message.detected_language,
        sent_at=message.sent_at,
        received_at=message.received_at,
        requires_attention=message.requires_attention,
        is_draft=message.is_draft,
        attachments=attachment_models,
    )


@router.get(
    "/{conversation_id}/messages/{message_id}/attachments/{attachment_id}",
    response_class=FileResponse,
    name="download_conversation_attachment",
)
async def download_attachment(
    conversation_id: int,
    message_id: int,
    attachment_id: int,
    service: ConversationService = Depends(get_conversation_service),
    attachment_service: AttachmentService = Depends(get_attachment_service),
    _user=Depends(get_current_active_user),
) -> FileResponse:
    attachment = await service.session.get(MessageAttachment, attachment_id)
    if (
        attachment is None
        or attachment.conversation_id != conversation_id
        or attachment.message_id != message_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
    file_path = attachment_service.resolve_path(attachment.storage_path)
    return FileResponse(
        file_path,
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.filename,
    )


@router.post("/{conversation_id}/close", status_code=status.HTTP_204_NO_CONTENT)
async def close_conversation(
    conversation_id: int,
    service: ConversationService = Depends(get_conversation_service),
    _superuser=Depends(ensure_superuser),
) -> Response:
    try:
        conversation = await service.get_conversation(conversation_id)
    except NoResultFound as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    await service.close_conversation(conversation)
    await service.session.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conversation_id}/scenario/assign", response_model=ScenarioStateRead)
async def assign_scenario(
    conversation_id: int,
    request: ScenarioAssignRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    scenario_service: ScenarioService = Depends(get_scenario_service),
    _superuser=Depends(ensure_superuser),
) -> ScenarioStateRead:
    conversation = await conversation_service.get_conversation(conversation_id)
    scenario = await scenario_service.get_scenario(request.scenario_id)
    starting_step = None
    if request.starting_step_id is not None:
        starting_step = next((step for step in scenario.steps if step.id == request.starting_step_id), None)
        if starting_step is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario step not found")
    state = await conversation_service.assign_scenario(conversation, scenario, starting_step=starting_step, notes=request.notes)
    await conversation_service.session.commit()
    return _scenario_state_read(state, include_steps=True)


@router.post("/{conversation_id}/scenario/advance", response_model=ScenarioStateRead)
async def advance_scenario(
    conversation_id: int,
    request: ScenarioAdvanceRequest,
    conversation_service: ConversationService = Depends(get_conversation_service),
    _superuser=Depends(ensure_superuser),
) -> ScenarioStateRead:
    conversation = await conversation_service.get_conversation(conversation_id)
    state = conversation.__dict__.get("scenario_state")
    if state is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Scenario is not assigned")
    step = None
    if request.step_id is not None:
        scenario = state.scenario
        if scenario is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Scenario is not assigned")
        step = next((s for s in scenario.steps if s.id == request.step_id), None)
        if step is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario step not found")
    await conversation_service.advance_scenario_step(state, step=step, direction=request.direction)
    if request.notes is not None:
        state.notes = request.notes
    await conversation_service.session.flush()
    await conversation_service.session.commit()
    return _scenario_state_read(state, include_steps=True)


@router.get("/{conversation_id}/logs", response_model=List[ConversationLogEntryRead])
async def list_logs(
    conversation_id: int,
    conversation_service: ConversationService = Depends(get_conversation_service),
    _user=Depends(get_current_active_user),
) -> List[ConversationLogEntryRead]:
    conversation = await conversation_service.get_conversation(conversation_id)
    logs = sorted(conversation.logs, key=lambda entry: entry.created_at)
    return [ConversationLogEntryRead.model_validate(entry) for entry in logs]


@router.post("/{conversation_id}/logs/notes", response_model=ConversationLogEntryRead)
async def add_log_note(
    conversation_id: int,
    payload: ConversationNoteCreate,
    conversation_service: ConversationService = Depends(get_conversation_service),
    _user=Depends(get_current_active_user),
) -> ConversationLogEntryRead:
    conversation = await conversation_service.get_conversation(conversation_id)
    entry = await conversation_service.log_event(
        conversation,
        ConversationLogEvent.NOTE,
        summary=payload.summary,
        actor=ConversationActor.MANAGER,
        details=payload.details,
        context=payload.context,
    )
    await conversation_service.session.commit()
    return ConversationLogEntryRead.model_validate(entry)

