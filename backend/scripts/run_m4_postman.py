"""Real HTTP acceptance, real E5 and Postman upstream. Only the guarded M3 test DB is reset."""

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = ROOT / "backend/.runtime"


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main():
    # Reuse the existing dedicated-DB guard, real corpus/embeddings and admin regression.
    from run_postman import main as verify_m3

    verify_m3()
    from app.auth.passwords import create_user
    from app.domain.serving_reader import pin_active

    password = secrets.token_hex(24)
    create_user("m4-owner", password, "user")
    create_user("m4-other", password, "user")
    values = {
        "username": "m4-owner",
        "username_other": "m4-other",
        "password": password,
        "serving_id": pin_active().serving_id,
    }
    environment = SCRATCH / "m4.environment.yaml"
    environment.write_text(
        yaml.safe_dump(
            {
                "name": "M4 isolated local acceptance",
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
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    logs, processes = [], []
    try:
        sim_log = SCRATCH / "m4-simulation.ndjson"
        sim_log.write_text("", encoding="utf-8")
        sim_out = sim_log.open("w", encoding="utf-8")
        sim_err = (SCRATCH / "m4-simulation.err").open("w", encoding="utf-8")
        logs.extend([sim_out, sim_err])
        simulation = subprocess.Popen(
            [
                "postman",
                "simulation",
                "run",
                str(ROOT / "postman/simulations/m4-openai.sim.yaml"),
                "--port",
                str(available_port()),
                "--output",
                "ndjson",
                "--no-history",
            ],
            cwd=ROOT,
            stdout=sim_out,
            stderr=sim_err,
            creationflags=flags,
        )
        processes.append(simulation)
        address = None
        for _ in range(100):
            if simulation.poll() is not None:
                raise RuntimeError("Postman simulation failed; see ignored m4-simulation.err")
            for line in sim_log.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event.get("event") == "listening":
                    address = event["url"].replace("localhost", "127.0.0.1") + "/openai/v1"
            if address:
                break
            time.sleep(0.2)
        if not address:
            raise RuntimeError("Simulation never reported listening")
        env = dict(
            os.environ,
            OPENAI_API_KEY="local-simulation-only",
            OPENAI_MODEL="gpt-4.1-mini",
            OPENAI_REWRITE_MODEL="gpt-4.1-mini",
            OPENAI_BASE_URL=address,
        )
        api_log = (SCRATCH / "m4-api.log").open("w", encoding="utf-8")
        logs.append(api_log)
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
                "18005",
            ],
            cwd=ROOT,
            env=env,
            stdout=api_log,
            stderr=api_log,
            creationflags=flags,
        )
        processes.append(api)
        for _ in range(100):
            if api.poll() is not None:
                raise RuntimeError("M4 API startup failed; see ignored m4-api.log")
            try:
                with urllib.request.urlopen("http://127.0.0.1:18005/health/ready", timeout=1) as r:
                    if r.status == 200:
                        break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("M4 API never became ready")
        run = subprocess.run(
            [
                "postman",
                "collection",
                "run",
                str(ROOT / "backend/contracts/postman/m4"),
                "-e",
                str(environment),
                "--no-report-events",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = (run.stdout + run.stderr).replace(password, "[redacted]")
        (SCRATCH / "m4-postman.log").write_text(output, encoding="utf-8")
        print("\n".join(output.splitlines()[-30:]))
        if run.returncode:
            raise RuntimeError(
                f"M4 Postman failed, exit {run.returncode}; see ignored m4-postman.log"
            )
        events = [json.loads(line) for line in sim_log.read_text(encoding="utf-8").splitlines()]
        count = sum(e.get("event") == "request" for e in events)
        if not count:
            raise RuntimeError("No upstream requests reached the simulation")
        print(f"M4 real API + real E5 + simulated OpenAI PASS; upstream request events: {count}")
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log in logs:
            log.close()
        environment.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
