"""Export the application contract without a DB connection or real signing key."""

import json
import os
import secrets
from pathlib import Path

os.environ.setdefault("JWT_SECRET", secrets.token_hex(32))
from app.main import create_app

target = Path(__file__).resolve().parents[1] / "contracts/openapi.json"
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(
    json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print("Exported backend/contracts/openapi.json")
