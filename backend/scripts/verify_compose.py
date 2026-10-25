"""Full clean Compose smoke. Removes only this invocation's unique test project/volumes."""

import json
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main():
    project = "vietlaw-m3-smoke-" + uuid4().hex[:8]
    scratch = ROOT / "backend/.runtime" / project
    scratch.mkdir(parents=True)
    config = scratch / "compose.env"
    config.write_text(
        "\n".join(
            [
                "POSTGRES_PASSWORD=" + secrets.token_hex(24),
                "RUNTIME_PASSWORD=" + secrets.token_hex(24),
                "JWT_SECRET=" + secrets.token_hex(32),
                "API_PORT=18004",
                "DB_PORT=55434",
                "OPENAI_API_KEY=local-simulation-only",
                "OPENAI_MODEL=gpt-4.1-mini",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    override = scratch / "override.yml"
    override.write_text(
        yaml.safe_dump(
            {
                "services": {
                    "api": {
                        "volumes": [{"type": "bind", "source": str(ROOT / "backend/.model-cache"),
                                     "target": "/models", "read_only": True}]
                    },
                    "worker": {
                        "volumes": [
                            {
                                "type": "bind",
                                "source": str(ROOT / "backend/.model-cache"),
                                "target": "/models",
                                "read_only": True,
                            }
                        ]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    compose = [
        "docker",
        "compose",
        "-p",
        project,
        "--env-file",
        str(config),
        "-f",
        str(ROOT / "infra/compose.m3.yml"),
        "-f",
        str(ROOT / "infra/compose.m4.yml"),
        "-f",
        str(override),
    ]

    def run(*args, input=None):
        result = subprocess.run(
            [*compose, *args],
            cwd=ROOT,
            input=input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                "Compose command failed: " + " ".join(args[:3]) + "\n" + result.stderr[-2000:]
            )
        return result.stdout.strip()

    base = "http://127.0.0.1:18004"
    token = None

    def request(path, body=None, authenticated=True, extra_headers=None):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + token
        headers.update(extra_headers or {})
        req = urllib.request.Request(
            base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        )
        # First API-side E5 query includes cold Python/model loading in the container.
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.load(response)

    try:
        run("up", "-d", "--no-build")
        for _ in range(60):
            try:
                if request("/health/ready", authenticated=False)["status"] == "ready":
                    break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError("Compose API not ready")
        password = secrets.token_hex(24)
        run(
            "exec",
            "-T",
            "api",
            "python",
            "-",
            input="from app.auth.passwords import create_user\ncreate_user('compose-smoke',"
            + repr(password)
            + ")\n",
        )
        token = request(
            "/api/v1/auth/token", {"username": "compose-smoke", "password": password}, False
        )["access_token"]
        run("cp", str(ROOT / "data/manifests/m1/labor-corpus-v1.json"), "api:/tmp/m1.json")
        corpus = run(
            "exec", "-T", "api", "python", "-m", "app.cli", "register-release", "/tmp/m1.json"
        )
        assert corpus == "6ebc3836a333f2239e524d6016c0bdf7c11abe6751c4a1b9cd01185e74fb84b7"
        profile = run("exec", "-T", "worker", "python", "-m", "app.cli", "register-profile")

        def poll(job):
            for _ in range(180):
                current = request("/api/v1/admin/jobs/" + job["id"])
                if current["state"] == "succeeded":
                    return current
                if current["state"] == "failed":
                    raise RuntimeError("Compose job failed: " + str(current["error"]))
                time.sleep(1)
            raise RuntimeError("Compose job timed out")

        imported = request("/api/v1/admin/imports", {"release_id": corpus})
        assert poll(imported)["counts"]["succeeded"] == 10
        assert request("/api/v1/admin/imports", {"release_id": corpus})["id"] == imported["id"]
        embedded = request(
            "/api/v1/admin/embedding-jobs",
            {"corpus_snapshot_id": corpus, "embedding_profile_id": profile},
        )
        assert poll(embedded)["counts"]["succeeded"] == 10
        snapshot = request(
            "/api/v1/admin/serving-snapshots",
            {"corpus_snapshot_id": corpus, "embedding_profile_id": profile},
        )
        url = "/api/v1/admin/serving-snapshots/" + snapshot["id"]
        request(
            url + "/review",
            {
                "decision": "approve",
                "note": "Clean Compose acceptance; existing M1 review retained",
            },
        )
        assert request(url + "/activate", {"expected_active_id": None})["state"] == "sealed"
        assert request(url)["chunk_count"] == 10
        result = run(
            "exec",
            "-T",
            "api",
            "python",
            "-",
            input="from datetime import date\nfrom app.domain.serving_reader import pin_active,read_chunks\nassert len(read_chunks(pin_active(),date(2026,2,12)))==10\nprint('Pinned reader: 10 chunks')\n",
        )
        print(result)
        candidates = request("/api/v1/search", {"query": "hợp đồng", "mode": "vector",
                                               "as_of_date": "2026-02-12"})
        assert candidates and candidates[0]["serving_snapshot_id"] == snapshot["id"]
        conversation = request("/api/v1/conversations", {})
        clarification = request("/api/v1/conversations/" + conversation["id"] + "/messages",
            {"question": "Luật hiện nay?"}, extra_headers={"Idempotency-Key": "compose-date"})
        assert clarification["status"] == "needs_clarification"
        print("Clean Compose + real E5 query + chat date policy: PASS (no live OpenAI call)")
    finally:
        teardown = subprocess.run(
            [*compose, "down", "--volumes"], cwd=ROOT, capture_output=True, text=True, check=False
        )
        config.unlink(missing_ok=True)
        if teardown.returncode:
            print("Test project teardown requires inspection: " + project)


if __name__ == "__main__":
    main()
