import json
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

root = Path(__file__).resolve().parents[2]
cfg = json.loads((root / "backend/.runtime/verification.json").read_text(encoding="utf-8"))
os.environ["DATABASE_URL"] = cfg["MIGRATION_DATABASE_URL"]
os.environ["JWT_SECRET"] = cfg["JWT_SECRET"]
command.upgrade(Config(str(root / "backend/alembic.ini")), "head")
command.upgrade(Config(str(root / "backend/alembic.ini")), "head")
with create_engine(cfg["MIGRATION_DATABASE_URL"]).begin() as conn:
    conn.execute(text("GRANT USAGE ON SCHEMA public TO vietlaw_app"))
    conn.execute(
        text("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO vietlaw_app")
    )
print("Migration head applied twice; runtime role has DML only")
