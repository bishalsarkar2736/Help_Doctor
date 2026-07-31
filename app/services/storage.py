"""One seam for every stored file.

Clinic logos, doctor credential documents and doctor signatures were each
written straight to the local filesystem by the service that owned them, with
`Path(...).write_bytes()` inline and the resulting path stored in the database.
That works while exactly one machine serves the app: the compose file shares
`uploads_data` and `media_data` between the api and celery_worker containers,
so both see the same files.

It stops working the moment a second api replica runs anywhere else — an upload
lands on replica A's disk, the row in the database points at a path that only
exists there, and a download served by replica B is a 404. This module exists so
that becoming true is a change in ONE place instead of seven.

Deliberately not an object-storage migration yet. `LocalFilesystemStorage`
reproduces exactly what the services did before, byte for byte and path for
path, so nothing about the running system changes and no data has to move. The
next step adds an S3/MinIO implementation of the same protocol.

KEYS ARE THE EXISTING RELATIVE PATHS
------------------------------------
A key looks like "uploads/doctor_documents/doctor7_bmdc_ab12.png" — precisely
what is already stored in doctor_documents.file_path and
doctors.signature_file_path. Keeping that shape means:

  * no alembic data migration and no rewrite of existing rows,
  * a row written before this refactor and one written after are identical,
  * and an S3 backend can use the same string as its object key.

Keys are therefore untrusted-ish input when they come back from the database,
so `_resolve` refuses anything that escapes the storage root — a stored path of
"../../etc/passwd" must not be readable through here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Storage(Protocol):
    """What the application needs of a file store, and nothing more."""

    def write(self, key: str, data: bytes) -> str:
        """Store `data` at `key`. Returns the key as persisted on the model."""
        ...

    def read(self, key: str) -> bytes:
        """Return the stored bytes. Raises FileNotFoundError if absent."""
        ...

    def delete(self, key: str) -> None:
        """Remove the object. Must not raise if it is already gone."""
        ...

    def exists(self, key: str) -> bool:
        ...

    def local_path(self, key: str) -> Path | None:
        """Filesystem path, or None if this backend has no such thing.

        The one concession to the current implementation. Two callers hand a
        real path to something outside our control — FileResponse streaming a
        credential document, and reportlab embedding a signature into a PDF.
        An object-storage backend returns None there and the caller falls back
        to `read()`; writing those call sites against bytes now is what keeps
        the eventual swap from touching them.
        """
        ...


class LocalFilesystemStorage:
    """The behaviour the services had before this module existed.

    Paths resolve relative to the process working directory, which is /app in
    the container and the repository root in development — the same assumption
    the inline `Path("uploads/...")` calls were already making.
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or Path.cwd()).resolve()

    def _resolve(self, key: str) -> Path:
        path = (self._root / key).resolve()

        # A key arriving from the database must not be able to address anything
        # outside the storage root.
        if not path.is_relative_to(self._root):
            raise ValueError(f"key escapes storage root: {key!r}")

        return path

    def write(self, key: str, data: bytes) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def read(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def delete(self, key: str) -> None:
        self._resolve(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def local_path(self, key: str) -> Path | None:
        return self._resolve(key)


class S3Storage:
    """S3-compatible object storage (MinIO in compose, S3/R2 in production).

    Keys are unchanged from the filesystem backend — "uploads/doctor_documents/
    doctorN_x.pdf" is used verbatim as the object key — so switching backends
    needs no database migration and rows written under either one resolve.

    Note on blocking: boto3 is synchronous, and so is the Storage protocol,
    matching the filesystem backend it replaces. Calls therefore block the
    event loop for the duration of a request to the object store. That is
    acceptable at current sizes (documents are capped at 5 MB and the store is
    on the same network) but is the first thing to revisit if uploads grow —
    the fix is to make the protocol async, which the seam now makes tractable.
    """

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        region: str,
    ) -> None:
        # Imported here, not at module scope: the filesystem backend must keep
        # working in environments that never install boto3 (and in tests).
        import boto3
        from botocore.config import Config as BotoConfig

        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            # path-style addressing: MinIO does not serve virtual-host style
            # buckets (bucket.host) without extra DNS setup.
            config=BotoConfig(s3={"addressing_style": "path"}),
        )

    def _is_missing(self, error: Exception) -> bool:
        code = getattr(error, "response", {}).get("Error", {}).get("Code", "")
        return str(code) in {"404", "NoSuchKey", "NotFound"}

    def write(self, key: str, data: bytes) -> str:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        return key

    def read(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            obj = self._client.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            # Callers catch FileNotFoundError — notably the PDF renderer, which
            # must degrade to an unsigned prescription rather than 500.
            if self._is_missing(exc):
                raise FileNotFoundError(key) from exc
            raise

        return obj["Body"].read()

    def delete(self, key: str) -> None:
        # S3 delete_object is already idempotent: removing a missing key is a
        # success, which is the contract the protocol requires.
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if self._is_missing(exc):
                return False
            raise

        return True

    def local_path(self, key: str) -> Path | None:
        # No filesystem path exists. Callers fall back to read().
        return None


_storage: Storage | None = None


def _build_storage() -> Storage:
    from app.config import get_settings

    settings = get_settings()

    if settings.STORAGE_BACKEND == "s3":
        return S3Storage(
            bucket=settings.S3_BUCKET,
            endpoint_url=settings.S3_ENDPOINT_URL,
            access_key=settings.S3_ACCESS_KEY,
            secret_key=settings.S3_SECRET_KEY,
            region=settings.S3_REGION,
        )

    return LocalFilesystemStorage()


def get_storage() -> Storage:
    """The process-wide storage backend.

    A module-level singleton rather than a FastAPI dependency because celery
    tasks and the PDF renderer need it too, and neither has a request scope.
    """
    global _storage

    if _storage is None:
        _storage = _build_storage()

    return _storage


def set_storage(storage: Storage | None) -> None:
    """Swap the backend. For tests, and for wiring a real one at startup."""
    global _storage
    _storage = storage
