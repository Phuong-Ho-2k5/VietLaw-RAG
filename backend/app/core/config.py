from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    database_url: str = "postgresql+psycopg://localhost/vietlaw"
    jwt_secret: str = Field(min_length=32)
    jwt_issuer: str = "vietlaw"
    jwt_audience: str = "vietlaw-admin"
    release_dir: Path = Path(__file__).resolve().parents[2] / ".runtime/releases"
    model_cache: Path = Path(__file__).resolve().parents[2] / ".model-cache"
    max_release_bytes: int = 64 * 1024 * 1024
    max_chunks: int = 10000
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    openai_rewrite_model: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    provider_timeout: float = Field(default=20, gt=0, le=20)
    pipeline_timeout: float = Field(default=60, gt=0, le=60)
    evidence_token_budget: int = Field(default=6000, ge=1, le=6000)
    input_token_budget: int = Field(default=10000, ge=1, le=10000)
    generation_output_tokens: int = Field(default=2000, ge=1, le=2000)
    rewrite_output_tokens: int = Field(default=512, ge=1, le=512)
