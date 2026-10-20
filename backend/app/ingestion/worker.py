"""DB-backed worker with lease heartbeat and fenced per-item transactions."""

import logging
import threading
import time
from uuid import uuid4

from sqlalchemy.exc import OperationalError

from app.core.errors import DomainError
from app.ingestion import service
from app.ingestion.jobs import claim, finish, heartbeat


def run_once(worker_id: str) -> bool:
    job = claim(worker_id)
    if not job:
        return False
    stopped = threading.Event()

    def maintain_lease():
        while not stopped.wait(30):
            try:
                heartbeat(job)
            except Exception:
                logging.getLogger("vietlaw.worker").warning(
                    "Lease heartbeat failed for %s", job["id"]
                )
                return

    thread = threading.Thread(target=maintain_lease, daemon=True)
    thread.start()
    try:
        for attempt in range(4):
            try:
                if job["kind"] == "import":
                    service.import_release(job)
                else:
                    from app.ingestion.embedding_jobs import embed_release

                    embed_release(job)
                finish(job)
                break
            except (OSError, TimeoutError, OperationalError):
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
    except DomainError as exc:
        if exc.code != "STALE_WORKER":
            finish(job, exc.code)
    except Exception:
        logging.getLogger("vietlaw.worker").exception("Job %s failed", job["id"])
        try:
            finish(job, "WORKER_ERROR")
        except DomainError:
            pass
    finally:
        stopped.set()
        thread.join(timeout=2)
    return True


if __name__ == "__main__":
    identity = str(uuid4())
    while True:
        if not run_once(identity):
            time.sleep(1)
