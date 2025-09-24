from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import NoResultFound

from app.models.enums import ConversationActor, ConversationLogEvent, MessageSender
from app.models.scenario import ConversationScenarioState, ScenarioStep
from app.schemas import (
    ConversationDetail,
    ConversationLogEntryRead,
    ConversationNoteCreate,
    ConversationSummary,
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
from app.services.auth_service import ensure_superuser, get_current_active_user
from app.services.conversation_service import ConversationService
from app.services.scenario_service import ScenarioService

from ..deps import get_conversation_service, get_scenario_service

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
    service: ConversationService = Depends(get_conversation_service),
    _user=Depends(get_current_active_user),
) -> ConversationDetail:
    try:
        conversation = await service.get_conversation(conversation_id)
    except NoResultFound as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    messages = [
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
        )
        for message in conversation.messages
    ]
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
    payload: MessageSendRequest,
    service: ConversationService = Depends(get_conversation_service),
    _user=Depends(get_current_active_user),
) -> MessageRead:
    try:
        conversation = await service.get_conversation(conversation_id)
    except NoResultFound as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    sender_type = (
        MessageSender.ASSISTANT if payload.send_mode == "approve_ai" else MessageSender.MANAGER
    )

    message = await service.record_outbound_message(conversation, payload, sender_type)
    await service.session.commit()
    await service.session.refresh(message)

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

