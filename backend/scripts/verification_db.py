"""Create an isolated disposable M3 verification database; never touches user volumes."""

import json
import secrets
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "backend/.runtime/verification.json"
NAME = "vietlaw-m3-verification"


def main():
    if STATE.exists():
        print("Existing verification configuration preserved")
        return
    password = secrets.token_hex(24)
    runtime = secrets.token_hex(24)
    result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            NAME,
            "--label",
            "vietlaw.purpose=m3-verification",
            "-p",
            "127.0.0.1:55433:5432",
            "-e",
            "POSTGRES_USER=vietlaw_owner",
            "-e",
            "POSTGRES_DB=vietlaw_test",
            "-e",
            "POSTGRES_PASSWORD=" + password,
            "pgvector/pgvector:0.8.2-pg17",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError("Cannot create isolated verification container; inspect Docker state")
    for _ in range(60):
        ready = subprocess.run(
            ["docker", "exec", NAME, "pg_isready", "-U", "vietlaw_owner", "-d", "vietlaw_test"],
            capture_output=True,
        )
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("Verification PostgreSQL did not become ready")
    from sqlalchemy import create_engine

    url = f"postgresql+psycopg://vietlaw_owner:{password}@127.0.0.1:55433/vietlaw_test"
    with create_engine(url).begin() as conn:
        conn.exec_driver_sql("CREATE ROLE vietlaw_app LOGIN PASSWORD '" + runtime + "'")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps(
            {
                "MIGRATION_DATABASE_URL": url,
                "DATABASE_URL": f"postgresql+psycopg://vietlaw_app:{runtime}@127.0.0.1:55433/vietlaw_test",
                "JWT_SECRET": secrets.token_hex(32),
                "RELEASE_DIR": str(ROOT / "backend/.runtime/test-releases"),
            }
        ),
        encoding="utf-8",
    )
    print("Isolated verification PostgreSQL ready on 127.0.0.1:55433 (credentials stored locally)")


if __name__ == "__main__":
    main()
