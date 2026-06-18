"""Storage interface: local filesystem (dev) and Cloudflare R2 / S3 (prod).

Everything in the pipeline reads/writes through ``get_storage()`` so the two
backends are interchangeable. Keys look like ``jobs/<job_id>/uploads/<name>``.
"""
from __future__ import annotations

import shutil
import time
from abc import ABC, abstractmethod
from pathlib import Path

from .config import settings


class Storage(ABC):
    @abstractmethod
    def save_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        """Persist raw bytes at ``key``. Returns the storage key."""

    @abstractmethod
    def save_file(self, key: str, src_path: str, content_type: str | None = None) -> str:
        """Persist a file from disk at ``key``. Returns the storage key."""

    @abstractmethod
    def local_path(self, key: str) -> str:
        """Return a path on the local filesystem for reading.

        For R2 this downloads to a temp cache first; pipeline stages need real
        files to hand to ffmpeg/opencv.
        """

    @abstractmethod
    def public_url(self, key: str) -> str:
        """A URL the browser can fetch (for results)."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int:
        """Delete everything under a prefix (used by the 48h cleanup)."""


class LocalStorage(Storage):
    def __init__(self, root: Path, public_base_url: str):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.public_base_url = public_base_url.rstrip("/")

    def _abs(self, key: str) -> Path:
        p = (self.root / key).resolve()
        # Prevent path traversal outside the storage root.
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError(f"Illegal storage key: {key}")
        return p

    def save_bytes(self, key, data, content_type=None):
        p = self._abs(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    def save_file(self, key, src_path, content_type=None):
        p = self._abs(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        if Path(src_path).resolve() != p:
            shutil.copyfile(src_path, p)
        return key

    def local_path(self, key):
        return str(self._abs(key))

    def public_url(self, key):
        return f"{self.public_base_url}/{key}"

    def exists(self, key):
        return self._abs(key).exists()

    def delete(self, key):
        p = self._abs(key)
        if p.exists():
            p.unlink()

    def delete_prefix(self, prefix):
        base = self._abs(prefix)
        n = 0
        if base.is_dir():
            for f in base.rglob("*"):
                if f.is_file():
                    f.unlink()
                    n += 1
            shutil.rmtree(base, ignore_errors=True)
        return n


class R2Storage(Storage):
    """S3-compatible storage (Cloudflare R2). Lazily imports boto3."""

    def __init__(self):
        import boto3  # local import so dev without boto3 still works

        self.bucket = settings.r2_bucket
        self.public_base_url = settings.r2_public_base_url.rstrip("/")
        endpoint = settings.r2_endpoint_url or (
            f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
        )
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )
        self._cache = Path("/tmp/reelmagic_r2_cache")
        self._cache.mkdir(parents=True, exist_ok=True)

    def save_bytes(self, key, data, content_type=None):
        extra = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        return key

    def save_file(self, key, src_path, content_type=None):
        extra = {"ContentType": content_type} if content_type else {}
        self.client.upload_file(src_path, self.bucket, key, ExtraArgs=extra or None)
        return key

    def local_path(self, key):
        dst = self._cache / key
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(self.bucket, key, str(dst))
        return str(dst)

    def public_url(self, key):
        if self.public_base_url:
            return f"{self.public_base_url}/{key}"
        # Fall back to a time-limited presigned URL.
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=60 * 60 * 24,
        )

    def exists(self, key):
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def delete_prefix(self, prefix):
        paginator = self.client.get_paginator("list_objects_v2")
        n = 0
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objs = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if objs:
                self.client.delete_objects(
                    Bucket=self.bucket, Delete={"Objects": objs}
                )
                n += len(objs)
        return n


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        if settings.storage_backend == "r2":
            _storage = R2Storage()
        else:
            _storage = LocalStorage(
                settings.local_storage_path, settings.storage_public_base_url
            )
    return _storage


# --- key helpers -----------------------------------------------------------
def upload_key(job_id: str, filename: str) -> str:
    safe = Path(filename).name.replace(" ", "_")
    return f"jobs/{job_id}/uploads/{int(time.time()*1000)}_{safe}"


def work_key(job_id: str, name: str) -> str:
    return f"jobs/{job_id}/work/{name}"


def result_key(job_id: str) -> str:
    return f"jobs/{job_id}/result/reel.mp4"
