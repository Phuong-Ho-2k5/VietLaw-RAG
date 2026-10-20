from pathlib import Path

from pydantic import Field
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
