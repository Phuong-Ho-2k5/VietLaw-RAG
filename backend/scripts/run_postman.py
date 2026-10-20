"""Destructive only to the isolated verification database; starts/stops its own local API."""

import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]


def main():
    cfg = json.loads((ROOT / "backend/.runtime/verification.json").read_text(encoding="utf-8"))
    owner_url = cfg["MIGRATION_DATABASE_URL"]
    if not owner_url.endswith("@127.0.0.1:55433/vietlaw_test"):
        raise RuntimeError("Refusing to reset a database outside the dedicated verification target")
    for key in ("DATABASE_URL", "JWT_SECRET", "RELEASE_DIR"):
        os.environ[key] = cfg[key]
    from app.db.models import metadata

    with create_engine(owner_url).begin() as conn:
        conn.execute(
            text(
                "TRUNCATE "
                + ",".join('"' + t.name + '"' for t in metadata.sorted_tables)
                + " CASCADE"
            )
        )
        conn.execute(text("INSERT INTO active_corpus(singleton) VALUES (true)"))
    from app.auth.passwords import create_user
    from app.ingestion.embedding_jobs import enqueue_embeddings
    from app.ingestion.jobs import enqueue_import, get_job
    from app.ingestion.releases import register_release
    from app.ingestion.worker import run_once
    from app.providers.embedding import default_profile, register_profile

    password = secrets.token_hex(24)
    actor = create_user("postman-verification", password)
    corpus = register_release(ROOT / "data/manifests/m1/labor-corpus-v1.json")
    job = enqueue_import(corpus, actor)
    run_once("postman-import")
    if get_job(job["id"])["state"] != "succeeded":
        raise RuntimeError("Import failed")
    profile = register_profile(default_profile())
    job = enqueue_embeddings(corpus, profile, actor)
    run_once("postman-real-embedding")
    if get_job(job["id"])["state"] != "succeeded":
        raise RuntimeError("Real embeddings failed")
    values = {
        "username": "postman-verification",
        "password": password,
        "corpus_id": corpus,
        "profile_id": profile,
    }
    environment = ROOT / "backend/.runtime/postman.environment.yaml"
    environment.write_text(
        yaml.safe_dump(
            {
                "name": "Isolated local verification",
                "values": [
                    {
                        "key": k,
                        "value": v,
                        "enabled": True,
                        "type": "secret" if k == "password" else "default",
                    }
                    for k, v in values.items()
                ],
            }
        ),
        encoding="utf-8",
    )
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    log = (ROOT / "backend/.runtime/api.log").open("w", encoding="utf-8")
    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            "18003",
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        stdout=log,
        stderr=log,
        creationflags=creationflags,
    )
    try:
        for _ in range(40):
            if api.poll() is not None:
                raise RuntimeError("Local API failed to start; see ignored api.log")
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:18003/health/ready", timeout=1
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("Local API did not become ready")
        run = subprocess.run(
            [
                "postman",
                "collection",
                "run",
                str(ROOT / "backend/contracts/postman/m3"),
                "-e",
                str(environment),
                "--no-report-events",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = run.stdout + run.stderr
        (ROOT / "backend/.runtime/postman-run.log").write_text(
            output.replace(password, "[redacted]"), encoding="utf-8"
        )
        print("\n".join(output.replace(password, "[redacted]").splitlines()[-30:]))
        if run.returncode:
            raise RuntimeError("Postman assertions failed; see ignored postman-run.log")
        print("Postman real API acceptance passed; run events disabled")
    finally:
        api.terminate()
        try:
            api.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api.kill()
            api.wait(timeout=10)
        log.close()
        environment.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
