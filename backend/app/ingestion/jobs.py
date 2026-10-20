from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.core.errors import DomainError
from app.db.models import ingestion_job_items as items
from app.db.models import ingestion_jobs as jobs
from app.db.models import review_events
from app.db.session import engine
from app.ingestion.releases import release_path


def enqueue(kind: str, identity: str, payload: dict, actor_id: UUID):
    with engine().begin() as conn:
        conn.execute(
            insert(jobs)
            .values(id=uuid4(), kind=kind, identity=identity, payload=payload, actor_id=actor_id)
            .on_conflict_do_nothing(index_elements=[jobs.c.identity])
        )
        identifier = conn.scalar(select(jobs.c.id).where(jobs.c.identity == identity))
    return get_job(identifier)


def enqueue_import(release_id: str, actor_id: UUID):
    if not release_path(release_id).is_file():
        raise DomainError("RELEASE_NOT_REGISTERED", 404)
    return enqueue("import", "import:" + release_id, {"release_id": release_id}, actor_id)


def get_job(identifier: UUID):
    with engine().connect() as conn:
        row = conn.execute(select(jobs).where(jobs.c.id == identifier)).mappings().first()
        if not row:
            raise DomainError("JOB_NOT_FOUND", 404)
        counts = dict(
            conn.execute(
                select(items.c.state, func.count())
                .where(items.c.job_id == identifier)
                .group_by(items.c.state)
            ).all()
        )
        item_errors = (
            conn.execute(
                select(items.c.item_id, items.c.state, items.c.error).where(
                    items.c.job_id == identifier, items.c.error.is_not(None)
                )
            )
            .mappings()
            .all()
        )
        return {
            "id": row["id"],
            "kind": row["kind"],
            "state": row["state"],
            "attempt": row["attempt"],
            "error": row["error"],
            "errors": row["errors"],
            "counts": counts,
            "item_errors": [dict(e) for e in item_errors],
        }


def claim(worker_id: str):
    now = datetime.now(timezone.utc)
    with engine().begin() as conn:
        row = (
            conn.execute(
                select(jobs)
                .where(
                    or_(
                        jobs.c.state == "queued",
                        (jobs.c.state == "running") & (jobs.c.lease_until < now),
                    )
                )
                .order_by(jobs.c.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            .mappings()
            .first()
        )
        if not row:
            return None
        fence = uuid4()
        conn.execute(
            jobs.update()
            .where(jobs.c.id == row["id"])
            .values(
                state="running",
                worker_id=worker_id,
                fence=fence,
                lease_until=now + timedelta(seconds=120),
                attempt=row["attempt"] + 1,
                error=None,
            )
        )
        return dict(row, state="running", fence=fence, attempt=row["attempt"] + 1)


def assert_claim(conn, job):
    row = (
        conn.execute(select(jobs).where(jobs.c.id == job["id"]).with_for_update()).mappings().one()
    )
    if (
        row["state"] != "running"
        or row["fence"] != job["fence"]
        or row["lease_until"] <= datetime.now(timezone.utc)
    ):
        raise DomainError("STALE_WORKER")
    return row


def heartbeat(job):
    with engine().begin() as conn:
        assert_claim(conn, job)
        conn.execute(
            jobs.update()
            .where(jobs.c.id == job["id"])
            .values(lease_until=datetime.now(timezone.utc) + timedelta(seconds=120))
        )


def finish(job, error=None):
    with engine().begin() as conn:
        row = assert_claim(conn, job)
        history = row["errors"] + ([{"attempt": row["attempt"], "code": error}] if error else [])
        conn.execute(
            jobs.update()
            .where(jobs.c.id == job["id"])
            .values(
                state="failed" if error else "succeeded",
                error=error,
                errors=history,
                lease_until=None,
            )
        )


def retry_job(identifier: UUID, actor_id: UUID):
    with engine().begin() as conn:
        row = (
            conn.execute(select(jobs).where(jobs.c.id == identifier).with_for_update())
            .mappings()
            .first()
        )
        if not row:
            raise DomainError("JOB_NOT_FOUND", 404)
        if row["state"] != "failed":
            raise DomainError("JOB_NOT_RETRYABLE")
        conn.execute(
            jobs.update()
            .where(jobs.c.id == identifier)
            .values(state="queued", fence=None, lease_until=None, error=None)
        )
        conn.execute(
            items.update()
            .where(items.c.job_id == identifier, items.c.state != "succeeded")
            .values(state="pending", error=None)
        )
        conn.execute(
            review_events.insert().values(
                actor_id=actor_id,
                object_id=str(identifier),
                decision="retry",
                note="Retry unfinished items",
            )
        )
    return get_job(identifier)


def prepare_items(conn, job, identifiers):
    for identifier in identifiers:
        conn.execute(
            insert(items)
            .values(job_id=job["id"], item_id=identifier, state="pending")
            .on_conflict_do_nothing()
        )


def item_done(conn, job, identifier):
    return (
        conn.scalar(
            select(items.c.state).where(items.c.job_id == job["id"], items.c.item_id == identifier)
        )
        == "succeeded"
    )


def mark_item(conn, job, identifier, state, error=None):
    conn.execute(
        items.update()
        .where(items.c.job_id == job["id"], items.c.item_id == identifier)
        .values(state=state, error=error, attempt=items.c.attempt + 1)
    )
