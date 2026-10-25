from fastapi import FastAPI
from sqlalchemy import text

from app.api.schemas import ErrorResponse
from app.core.config import Settings
from app.core.errors import DomainError, install_errors
from app.db.session import engine_for


def create_app() -> FastAPI:
    from app.api.admin_snapshots import router as snapshots
    from app.api.chat import router as chat
    from app.api.router import router as admin
    from app.api.search import router as search
    from app.auth.routes import router as auth

    settings = Settings()
    app = FastAPI(
        title="VietLaw RAG",
        version="0.4.0",
        responses={
            status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422, 500, 502, 503, 504)
        },
    )
    install_errors(app)
    app.include_router(auth)
    app.include_router(admin)
    app.include_router(snapshots)
    app.include_router(search)
    app.include_router(chat)

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        try:
            with engine_for(settings.database_url).connect() as conn:
                version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                extension = conn.execute(
                    text("SELECT 1 FROM pg_extension WHERE extname='vector'")
                ).scalar()
                if version != "0004" or not extension:
                    raise ValueError("migration/extension mismatch")
        except Exception:
            raise DomainError("NOT_READY", 503, "Database migration or extension unavailable")
        return {"status": "ready"}

    return app
