from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str


class JobError(BaseModel):
    attempt: int
    code: str


class ItemError(BaseModel):
    item_id: str
    state: str
    error: str | None


class JobDTO(BaseModel):
    id: UUID
    kind: Literal["import", "embedding"]
    state: Literal["queued", "running", "succeeded", "failed"]
    attempt: int
    error: str | None
    errors: list[JobError]
    counts: dict[str, int]
    item_errors: list[ItemError]


class ReviewEvent(BaseModel):
    actor_id: UUID
    decision: str
    note: str
    created_at: datetime


class SnapshotDTO(BaseModel):
    id: str
    corpus_snapshot_id: str
    embedding_profile_id: str
    state: Literal["draft", "ready", "approved", "rejected", "sealed"]
    chunk_count: int
    manifest_hash: str
    review_events: list[ReviewEvent] = Field(default_factory=list)
