from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.router import ProfileBody
from app.api.schemas import SnapshotDTO
from app.auth.dependencies import require_admin
from app.domain.snapshots import activate, build_serving_snapshot, get_snapshot, review_snapshot

router = APIRouter(
    prefix="/api/v1/admin/serving-snapshots",
    tags=["snapshots"],
    dependencies=[Depends(require_admin)],
)


class ReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=1, max_length=2000)


class ActivateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_active_id: str | None = Field(..., pattern=r"^[0-9a-f]{64}$")


@router.post("", status_code=201, response_model=SnapshotDTO)
def create(body: ProfileBody):
    return build_serving_snapshot(body.corpus_snapshot_id, body.embedding_profile_id)


@router.get("/{identifier}", response_model=SnapshotDTO)
def get(identifier: str):
    return get_snapshot(identifier)


@router.post("/{identifier}/review", response_model=SnapshotDTO)
def review(identifier: str, body: ReviewBody, admin=Depends(require_admin)):
    return review_snapshot(identifier, admin["id"], body.decision, body.note)


@router.post("/{identifier}/activate", response_model=SnapshotDTO)
def activation(identifier: str, body: ActivateBody, admin=Depends(require_admin)):
    return activate(identifier, body.expected_active_id, admin["id"])
