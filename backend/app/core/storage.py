"""
Where uploaded files live on disk (S4). Outside the git repo (STORAGE_DIR, default ~/datadna_storage).

  <STORAGE_DIR>/<course_file_id>/<submission_id>/v<N>_<first 12 of sha256>.<ext>

The user's own file name is never used on disk, only in the database.
Files are written to a temp file first, flushed to disk, then renamed into place.
"""
import hashlib
import os
import tempfile
from pathlib import Path

from app.core import settings

CHUNK = 1024 * 1024


class TooLarge(Exception):
    pass


def root() -> Path:
    path = Path(settings.storage_dir())
    path.mkdir(parents=True, exist_ok=True)
    return path


def receive(stream, limit_bytes: int) -> tuple[Path, int, str]:
    """
    Copy an upload stream to a temp file inside the storage folder, hashing as it goes.
    Stops as soon as limit_bytes is exceeded (raises TooLarge, temp file removed).
    Returns (temp_path, size, sha256_hex).
    """
    tmp_dir = root() / ".tmp"
    tmp_dir.mkdir(exist_ok=True)
    fd, name = tempfile.mkstemp(dir=tmp_dir, prefix="up_")
    tmp = Path(name)
    digest, size = hashlib.sha256(), 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit_bytes:
                    raise TooLarge()
                digest.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp, size, digest.hexdigest()


def discard(path: Path | None) -> None:
    if path is not None:
        Path(path).unlink(missing_ok=True)


def place(tmp: Path, course_file_id, submission_id, version_no: int, sha256: str, ext: str) -> str:
    """Move the temp file to its final place. Returns the storage_key (relative path)."""
    key = f"{course_file_id}/{submission_id}/v{version_no}_{sha256[:12]}.{ext}"
    final = root() / key
    final.parent.mkdir(parents=True, exist_ok=True)
    if final.exists():
        raise FileExistsError(key)  # never overwrite an earlier version
    os.replace(tmp, final)
    return key


def remove(storage_key: str | None) -> None:
    if storage_key:
        (root() / storage_key).unlink(missing_ok=True)


def resolve(storage_key: str) -> Path:
    """Absolute path for a stored key. Refuses anything that escapes the storage folder."""
    base = root().resolve()
    path = (base / storage_key).resolve()
    if base not in path.parents:
        raise ValueError("storage key escapes the storage folder")
    return path


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()
