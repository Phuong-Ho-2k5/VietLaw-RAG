from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Mode = Literal["keyword", "vector", "hybrid"]
Topic = Literal["contract", "probation", "wages", "hours_rest", "termination"]
Status = Literal["answered", "insufficient_evidence", "out_of_scope", "needs_clarification"]


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(DTO):
    question: str = Field(min_length=1, max_length=4000)
    mode: Mode = "hybrid"
    as_of_date: date | None = None
    topic: Topic | None = None

    @field_validator("question")
    @classmethod
    def trim_question(cls, value):
        if not value.strip():
            raise ValueError("Empty question")
        return value.strip()


class SearchRequest(DTO):
    query: str = Field(min_length=1, max_length=4000)
    mode: Mode = "hybrid"
    top_k: int = Field(default=5, ge=1, le=10)
    as_of_date: date
    topic: Topic | None = None

    @field_validator("query")
    @classmethod
    def trim_query(cls, value):
        return ChatRequest.trim_question(value)


class CandidateDTO(DTO):
    chunk_id: str
    corpus_snapshot_id: str
    serving_snapshot_id: str
    embedding_profile_id: str
    score: float
    rank: int
    provenance: dict
    branches: dict = Field(default_factory=dict)


class Claim(DTO):
    text: str
    source_ids: list[str]


class GenerationDraft(DTO):
    status: Status
    clarification_question: str | None
    claims: list[Claim]


class RewriteResult(DTO):
    standalone_question: str
    needs_clarification: bool
    reason: str
    fallback: bool = False


class HistoryMessage(DTO):
    role: Literal["user", "assistant"]
    text: str
    as_of_date: date | None = None


class TemporalDecision(DTO):
    as_of_date: date | None
    clarification: str | None = None
    scope_notice: str = ""


class ContextBundle(DTO):
    chunks: list[dict] = Field(default_factory=list)
    token_count: int = 0
    excluded_groups: list[str] = Field(default_factory=list)


class CitationDTO(DTO):
    id: UUID
    chunk_id: str
    version_id: str
    serving_snapshot_id: str
    start: int
    end: int
    quote: str
    metadata: dict


class ValidatedAnswer(DTO):
    status: Status
    answer: str
    claims: list[Claim] = Field(default_factory=list)
    citations: list[CitationDTO] = Field(default_factory=list)


class ChatResult(ValidatedAnswer):
    conversation_id: UUID
    message_id: UUID
    request_id: str
    corpus_snapshot_id: str
    serving_snapshot_id: str
    snapshot_id: str
    embedding_profile_id: str
    as_of_date: date | None
    scope_notice: str


class TraceDTO(DTO):
    data: dict = Field(default_factory=dict)


class TurnError(DTO):
    code: str
    status: int


class ReservedTurn(DTO):
    conversation_id: UUID
    message_id: UUID
    fence: UUID
    replay: dict | None = None


class ConversationDTO(DTO):
    id: UUID
    created_at: datetime


class ConversationPage(DTO):
    items: list[ConversationDTO]
    next_cursor: str | None


class MessageDTO(DTO):
    id: UUID
    sequence: int
    role: str
    text: str
    state: str
    result: dict | None
    error_code: str | None
    request_id: str


class MessagePage(DTO):
    items: list[MessageDTO]
    next_cursor: str | None
