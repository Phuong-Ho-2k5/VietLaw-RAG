from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from app.auth.dependencies import require_user
from app.chat import repository
from app.chat.schemas import (
    ChatRequest,
    ChatResult,
    CitationDTO,
    ConversationDTO,
    ConversationPage,
    MessagePage,
)
from app.chat.service import send_message

router = APIRouter(prefix="/api/v1", tags=["chat"])
PageLimit = Annotated[int, Query(ge=1, le=100)]


@router.post("/conversations", response_model=ConversationDTO, status_code=201)
def create_conversation(user=Depends(require_user)):
    return repository.create_conversation(user["id"])


@router.get("/conversations", response_model=ConversationPage)
def conversations(limit: PageLimit = 20, cursor: str | None = None, user=Depends(require_user)):
    return repository.list_conversations(user["id"], limit, cursor)


@router.post("/conversations/{conversation_id}/messages", response_model=ChatResult)
def chat_message(
    conversation_id: UUID,
    body: ChatRequest,
    request: Request,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128, pattern=r"^[!-~]+$")],
    user=Depends(require_user),
):
    return send_message(
        user["id"], conversation_id, body, idempotency_key, request.state.request_id
    )


@router.get("/conversations/{conversation_id}/messages", response_model=MessagePage)
def messages(
    conversation_id: UUID,
    limit: PageLimit = 20,
    cursor: str | None = None,
    user=Depends(require_user),
):
    return repository.list_messages(user["id"], conversation_id, limit, cursor)


@router.get("/messages/{message_id}/citations/{citation_id}", response_model=CitationDTO)
def citation(message_id: UUID, citation_id: UUID, user=Depends(require_user)):
    return repository.read_citation(user["id"], message_id, citation_id)


@router.get("/messages/{message_id}/trace", response_model=dict)
def trace(message_id: UUID, user=Depends(require_user)):
    return repository.read_trace(user["id"], message_id)
