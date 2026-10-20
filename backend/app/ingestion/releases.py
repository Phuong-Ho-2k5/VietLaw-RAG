import os
import re
import tempfile
from pathlib import Path

from app.core.config import Settings
from app.core.errors import DomainError
from app.ingestion.manifest import load_release


def release_path(identifier: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", identifier):
        raise DomainError("INVALID_RELEASE_ID", 422)
    return Settings().release_dir / (identifier + ".json")


def register_release(path: Path) -> str:
    release = load_release(path)
    target = release_path(release.corpus_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if load_release(target).corpus_id != release.corpus_id:
            raise DomainError("RELEASE_CONFLICT")
        return release.corpus_id
    # Atomic create through a fully written temporary file and hard link; never overwrite a registered release.
    fd, temporary = tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            import json

            json.dump(release.payload, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            load_release(target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return release.corpus_id
