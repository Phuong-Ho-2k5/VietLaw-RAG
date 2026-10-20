from uuid import UUID

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas import JobDTO
from app.auth.dependencies import require_admin
from app.ingestion.jobs import enqueue_import, get_job, retry_job

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/jobs/{job_id}", response_model=JobDTO)
def job(job_id: UUID):
    return get_job(job_id)


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/imports", status_code=202, response_model=JobDTO)
def create_import(body: ImportBody, response: Response, admin=Depends(require_admin)):
    result = enqueue_import(body.release_id, admin["id"])
    response.headers["Location"] = f"/api/v1/admin/jobs/{result['id']}"
    return result


@router.post("/jobs/{job_id}/retry", status_code=202, response_model=JobDTO)
def retry(job_id: UUID, admin=Depends(require_admin)):
    return retry_job(job_id, admin["id"])


class ProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    corpus_snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    embedding_profile_id: str = Field(pattern=r"^[0-9a-f]{64}$")


@router.post("/embedding-jobs", status_code=202, response_model=JobDTO)
def embedding_job(body: ProfileBody, response: Response, admin=Depends(require_admin)):
    from app.ingestion.embedding_jobs import enqueue_embeddings

    result = enqueue_embeddings(body.corpus_snapshot_id, body.embedding_profile_id, admin["id"])
    response.headers["Location"] = f"/api/v1/admin/jobs/{result['id']}"
    return result
