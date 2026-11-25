"""Firmware artifact storage: streamed uploads with SHA-256, and short-lived signed download links."""

from __future__ import annotations

import hashlib
import hmac
import re
import time
import uuid
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ResourceNotFound
from app.models.artifact import Artifact

CHUNK_SIZE = 1024 * 1024
_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


S3_PREFIX = "s3:"


def _s3_client():
    """boto3 S3 client for the configured bucket (credentials from the usual AWS environment/role)."""
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - depends on the install
        raise ArtifactError("ARTIFACT_STORAGE=s3 needs the boto3 package (pip install boto3)") from exc
    kwargs = {}
    if settings.artifact_s3_endpoint_url:
        kwargs["endpoint_url"] = settings.artifact_s3_endpoint_url
    if settings.artifact_s3_region:
        kwargs["region_name"] = settings.artifact_s3_region
    return boto3.client("s3", **kwargs)


def _s3_delete_quietly(key: str) -> None:
    try:
        _s3_client().delete_object(Bucket=settings.artifact_s3_bucket, Key=key)
    except Exception:  # noqa: BLE001 - an orphaned object is better than a failed request
        pass


class ArtifactError(ValueError):
    """The upload cannot be stored (empty, too large, unusable name)."""


class ArtifactTooLarge(ArtifactError):
    pass


def safe_name(value: str | None) -> str:
    """Reduce a client-supplied file name to a harmless base name."""
    base = (value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    cleaned = _UNSAFE_NAME_CHARS.sub("_", base).strip("._")
    if not cleaned:
        raise ArtifactError("artifact needs a file name")
    return cleaned[:128]


def storage_root() -> Path:
    root = Path(settings.artifact_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


class ArtifactService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------ storage

    def store(
        self,
        stream: BinaryIO,
        filename: str | None,
        uploaded_by: str,
        description: str | None = None,
        content_type: str | None = None,
    ) -> Artifact:
        name = safe_name(filename)
        artifact = Artifact(
            name=name,
            description=(description or "").strip()[:500] or None,
            size_bytes=0,
            sha256="",
            content_type=(content_type or "")[:100] or None,
            storage_path="",
            uploaded_by=uploaded_by,
        )
        artifact.id = str(uuid.uuid4())
        use_s3 = settings.artifact_storage == "s3"
        root = storage_root()
        relative = f"{artifact.id[:2]}/{artifact.id}"
        # Always stream to local disk first (computing the checksum); S3 uploads then copy it up.
        destination = root / (f".incoming-{artifact.id}" if use_s3 else relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        uploaded_key: str | None = None
        try:
            with destination.open("wb") as out:
                while chunk := stream.read(CHUNK_SIZE):
                    size += len(chunk)
                    if size > settings.artifact_max_bytes:
                        raise ArtifactTooLarge(
                            f"artifact exceeds the {settings.artifact_max_bytes} byte upload limit"
                        )
                    digest.update(chunk)
                    out.write(chunk)
            if size == 0:
                raise ArtifactError("artifact is empty")
            if use_s3:
                uploaded_key = f"{settings.artifact_s3_prefix}{relative}"
                _s3_client().upload_file(str(destination), settings.artifact_s3_bucket, uploaded_key)
                artifact.storage_path = S3_PREFIX + uploaded_key
                destination.unlink(missing_ok=True)
            else:
                artifact.storage_path = relative
            artifact.size_bytes = size
            artifact.sha256 = digest.hexdigest()
            self.db.add(artifact)
            self.db.commit()
        except BaseException:
            destination.unlink(missing_ok=True)
            if uploaded_key is not None:
                _s3_delete_quietly(uploaded_key)
            self.db.rollback()
            raise
        self.db.refresh(artifact)
        return artifact

    @staticmethod
    def is_remote(artifact: Artifact) -> bool:
        return artifact.storage_path.startswith(S3_PREFIX)

    def path_for(self, artifact: Artifact) -> Path:
        root = storage_root()
        path = (root / artifact.storage_path).resolve()
        if root not in path.parents:  # a corrupted row must never point outside the store
            raise ResourceNotFound("Artifact file", artifact.id)
        if not path.is_file():
            raise ResourceNotFound("Artifact file", artifact.id)
        return path

    def ensure_available(self, artifact: Artifact) -> None:
        """Raise ResourceNotFound when the stored file is missing."""
        if not self.is_remote(artifact):
            self.path_for(artifact)
            return
        try:
            _s3_client().head_object(Bucket=settings.artifact_s3_bucket, Key=artifact.storage_path[len(S3_PREFIX):])
        except Exception as exc:  # noqa: BLE001 - boto raises ClientError for 404/403 alike
            raise ResourceNotFound("Artifact file", artifact.id) from exc

    def presigned_download_url(self, artifact: Artifact, ttl_seconds: int = 300) -> str:
        return _s3_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.artifact_s3_bucket,
                "Key": artifact.storage_path[len(S3_PREFIX):],
                "ResponseContentDisposition": f'attachment; filename="{artifact.name}"',
            },
            ExpiresIn=ttl_seconds,
        )

    # ------------------------------------------------------------------ queries

    def get(self, artifact_id: str) -> Artifact:
        artifact = self.db.get(Artifact, artifact_id)
        if artifact is None:
            raise ResourceNotFound("Artifact", artifact_id)
        return artifact

    def list(self, uploaded_by: str | None = None, limit: int = 200) -> list[Artifact]:
        statement = select(Artifact).order_by(Artifact.created_at.desc()).limit(limit)
        if uploaded_by:
            statement = statement.where(Artifact.uploaded_by == uploaded_by)
        return list(self.db.scalars(statement).all())

    def delete(self, artifact: Artifact) -> None:
        remote_key = artifact.storage_path[len(S3_PREFIX):] if self.is_remote(artifact) else None
        root = storage_root()
        path = (root / artifact.storage_path).resolve()
        self.db.delete(artifact)
        self.db.commit()
        if remote_key is not None:
            _s3_delete_quietly(remote_key)
        elif root in path.parents:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------- signed links

    @staticmethod
    def _signature(artifact_id: str, expires: int) -> str:
        message = f"artifact-download:{artifact_id}:{expires}".encode()
        return hmac.new(settings.secret_key.encode(), message, hashlib.sha256).hexdigest()

    def signed_url(self, artifact: Artifact, ttl_seconds: int | None = None) -> str:
        ttl = ttl_seconds or settings.artifact_url_ttl_seconds
        expires = int(time.time()) + ttl
        base = settings.targethub_public_url.rstrip("/")
        return (
            f"{base}/api/v1/artifacts/{artifact.id}/download"
            f"?expires={expires}&signature={self._signature(artifact.id, expires)}"
        )

    @classmethod
    def verify_signature(cls, artifact_id: str, expires: int, signature: str) -> bool:
        if expires < int(time.time()):
            return False
        return hmac.compare_digest(cls._signature(artifact_id, expires), signature)

    # ----------------------------------------------------------- deploy support

    def resolve_deploy_params(self, params: dict) -> dict:
        """Expand ``artifact_id`` into the url/sha256/artifact/bytes fields the deploy paths use."""
        artifact_id = params.get("artifact_id")
        if not artifact_id:
            return params
        artifact = self.get(str(artifact_id))
        self.ensure_available(artifact)  # fail early if the file is gone
        resolved = {k: v for k, v in params.items() if k != "artifact_id"}
        resolved.update(
            url=self.signed_url(artifact),
            sha256=artifact.sha256,
            artifact=artifact.name,
            bytes=artifact.size_bytes,
        )
        return resolved
