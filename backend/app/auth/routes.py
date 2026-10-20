from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.auth.passwords import authenticate
from app.auth.tokens import issue_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 1800


@router.post("/token", response_model=Token)
def token(body: Login):
    return Token(access_token=issue_token(authenticate(body.username, body.password)["id"]))
