"""Exercise frozen migrations in a new disposable database on the verification server."""

import json
import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[2]
cfg = json.loads((root / "backend/.runtime/verification.json").read_text(encoding="utf-8"))
owner_url = make_url(cfg["MIGRATION_DATABASE_URL"])
if owner_url.host != "127.0.0.1" or owner_url.port != 55433 or owner_url.database != "vietlaw_test":
    raise RuntimeError("Only the dedicated verification server is allowed")
name = "m3_migration_" + uuid4().hex
admin = create_engine(owner_url, isolation_level="AUTOCOMMIT", hide_parameters=True)
with admin.connect() as conn:
    conn.exec_driver_sql('CREATE DATABASE "' + name + '"')
db = None
try:
    url = owner_url.set(database=name)
    os.environ["DATABASE_URL"] = url.render_as_string(hide_password=False)
    os.environ["JWT_SECRET"] = cfg["JWT_SECRET"]
    alembic = Config(str(root / "backend/alembic.ini"))
    command.upgrade(alembic, "head")
    command.upgrade(alembic, "head")
    db = create_engine(url, hide_parameters=True)
    with db.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0004"
        from app.db.models import metadata

        actual = set(
            conn.scalars(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
            )
        )
        assert actual == set(metadata.tables) | {"alembic_version"}
    print("Fresh frozen migration and repeat upgrade passed")
finally:
    if db is not None:
        db.dispose()
    with admin.connect() as conn:
        conn.exec_driver_sql('DROP DATABASE "' + name + '"')
    admin.dispose()
