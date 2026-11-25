"""Firmware artifacts: upload once, deploy by id through short-lived signed links."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, is_admin_user, require_operator
from app.core.config import settings
from app.repositories.audit_repository import AuditRepository
from app.services.artifact_service import ArtifactError, ArtifactService, ArtifactTooLarge
from app.services.audit_service import AuditService

router = APIRouter(prefix="/artifacts", tags=["Artifacts"])
DB = Annotated[Session, Depends(get_db)]


class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    size_bytes: int
    sha256: str
    content_type: str | None
    uploaded_by: str
    created_at: datetime


def _owned_or_admin(artifact, user) -> None:
    if artifact.uploaded_by != user.username and not is_admin_user(user):
        raise HTTPException(status_code=403, detail="forbidden")


@router.post("", response_model=ArtifactResponse, status_code=201)
def upload_artifact(
    request: Request,
    db: DB,
    file: Annotated[UploadFile, File(description="Firmware image")],
    description: Annotated[str | None, Form(max_length=500)] = None,
    user=Depends(require_operator),
):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.artifact_max_bytes + 1024 * 1024:
        raise HTTPException(status_code=413, detail="artifact exceeds the upload limit")
    try:
        artifact = ArtifactService(db).store(
            file.file,
            file.filename,
            uploaded_by=user.username,
            description=description,
            content_type=file.content_type,
        )
    except ArtifactTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ArtifactError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    AuditService(AuditRepository(db)).record(
        action="artifact.upload", user_id=user.username, detail=f"{artifact.name} {artifact.sha256[:12]}"
    )
    return artifact


@router.get("", response_model=list[ArtifactResponse])
def list_artifacts(
    db: DB,
    mine: bool = Query(default=False, description="Only artifacts uploaded by you"),
    user=Depends(get_current_user),
):
    # Everyone who can deploy may reuse any uploaded image; viewers cannot deploy, so they see nothing.
    if "viewer" in user.role_list and not ({"admin", "user"} & set(user.role_list)):
        return []
    return ArtifactService(db).list(uploaded_by=user.username if mine else None)


@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: str, db: DB, user=Depends(require_operator)):
    return ArtifactService(db).get(artifact_id)


@router.delete("/{artifact_id}", status_code=204)
def delete_artifact(artifact_id: str, db: DB, user=Depends(require_operator)):
    service = ArtifactService(db)
    artifact = service.get(artifact_id)
    _owned_or_admin(artifact, user)
    service.delete(artifact)
    AuditService(AuditRepository(db)).record(
        action="artifact.delete", user_id=user.username, detail=artifact.name
    )


@router.get("/{artifact_id}/download", include_in_schema=False)
def download_artifact(artifact_id: str, db: DB, expires: int = Query(), signature: str = Query()):
    """Signed link used by agents; no login. Links expire after ``ARTIFACT_URL_TTL_SECONDS``."""
    if not ArtifactService.verify_signature(artifact_id, expires, signature):
        raise HTTPException(status_code=403, detail="invalid or expired download link")
    service = ArtifactService(db)
    artifact = service.get(artifact_id)
    if service.is_remote(artifact):
        # The bytes come straight from the bucket; the redirect target is valid for five minutes.
        return RedirectResponse(service.presigned_download_url(artifact), status_code=302)
    return FileResponse(
        service.path_for(artifact),
        media_type="application/octet-stream",
        filename=artifact.name,
    )
