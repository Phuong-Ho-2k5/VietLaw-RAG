from fastapi import APIRouter, Depends

from app.auth.dependencies import require_user
from app.chat.schemas import CandidateDTO, SearchRequest
from app.domain.serving_reader import pin_active
from app.rag.retrieval import retrieve

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.post("/search", response_model=list[CandidateDTO])
def search(body: SearchRequest, user=Depends(require_user)):
    return retrieve(pin_active(), body.query, body.as_of_date, body.mode, body.top_k, body.topic)
