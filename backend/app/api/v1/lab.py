"""Waitlist, in-app notifications and admin lab settings."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    get_current_user,
    get_db,
    is_admin_user,
    require_operator,
    require_role,
)
from app.models.lab import WaitlistEntry
from app.repositories.audit_repository import AuditRepository
from app.schemas.reservation import NotificationResponse, WaitlistJoin, WaitlistResponse
from app.services.audit_service import AuditService
from app.services.lab_settings import WEBHOOK_EVENTS, LabSettings, ReservationPolicy, Webhook
from app.services.notifier import Notifier, deliver
from app.services.waitlist_service import WaitlistService

router = APIRouter(tags=["Lab"])
DB = Annotated[Session, Depends(get_db)]


def _present(service: WaitlistService, entry: WaitlistEntry) -> WaitlistResponse:
    response = WaitlistResponse.model_validate(entry)
    response.position = service.position(entry)
    return response


# --------------------------------------------------------------------------- waitlist


@router.get("/waitlist", response_model=list[WaitlistResponse])
def list_waitlist(
    db: DB,
    target_id: str | None = Query(default=None),
    include_all_users: bool = Query(default=False, alias="all"),
    user=Depends(get_current_user),
):
    """Your waitlist entries; with a target_id, the whole queue for that target."""
    service = WaitlistService(db)
    if target_id or (include_all_users and is_admin_user(user)):
        entries = service.list(target_id=target_id)
    else:
        entries = service.list(user_id=user.username)
    return [_present(service, entry) for entry in entries]


@router.post("/waitlist", response_model=WaitlistResponse, status_code=201)
def join_waitlist(request: WaitlistJoin, db: DB, user=Depends(require_operator)):
    service = WaitlistService(db)
    entry = service.join(
        user.username,
        target_id=request.target_id,
        tag=request.tag.strip().lower() if request.tag else None,
        duration_minutes=request.duration_minutes,
        note=request.note,
    )
    AuditService(AuditRepository(db)).record(
        action="waitlist.join", user_id=user.username, target_id=entry.target_id, detail=entry.tag
    )
    # The target may already be free.
    service.process()
    db.refresh(entry)
    return _present(service, entry)


@router.delete("/waitlist/{entry_id}", response_model=WaitlistResponse)
def leave_waitlist(entry_id: str, db: DB, user=Depends(get_current_user)):
    service = WaitlistService(db)
    entry = service.leave(user.username, entry_id, privileged=is_admin_user(user))
    return _present(service, entry)


# --------------------------------------------------------------------------- notifications


@router.get("/notifications", response_model=list[NotificationResponse])
def list_notifications(
    db: DB,
    unread: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    user=Depends(get_current_user),
):
    return Notifier(db).list_for(user.username, unread_only=unread, limit=limit)


@router.post("/notifications/read")
def mark_notifications_read(
    db: DB,
    notification_id: str | None = Query(default=None, alias="id"),
    user=Depends(get_current_user),
):
    return {"updated": Notifier(db).mark_read(user.username, notification_id)}


# --------------------------------------------------------------------------- settings


@router.get("/settings/policy", response_model=ReservationPolicy)
def get_policy(db: DB, _user=Depends(get_current_user)):
    """Reservation policy (readable by everyone so clients can show the limits)."""
    return LabSettings(db).policy()


@router.put("/settings/policy", response_model=ReservationPolicy)
def update_policy(policy: ReservationPolicy, db: DB, admin=Depends(require_role("admin"))):
    updated = LabSettings(db).update_policy(policy, admin.username)
    AuditService(AuditRepository(db)).record(
        action="settings.policy", user_id=admin.username, detail=str(policy.model_dump())
    )
    return updated


def _masked(hooks: list[Webhook]) -> list[dict]:
    return [{**hook.model_dump(mode="json"), "secret": "********" if hook.secret else None} for hook in hooks]


@router.get("/settings/webhooks")
def get_webhooks(db: DB, _admin=Depends(require_role("admin"))):
    return {"webhooks": _masked(LabSettings(db).webhooks()), "events": list(WEBHOOK_EVENTS)}


@router.put("/settings/webhooks")
def update_webhooks(body: dict, db: DB, admin=Depends(require_role("admin"))):
    raw = body.get("webhooks")
    if not isinstance(raw, list):
        raise HTTPException(status_code=422, detail="Body must be {\"webhooks\": [...]}")
    cleaned = []
    for item in raw:
        item = dict(item)
        if item.get("secret") == "********":
            item["secret"] = None  # unchanged
        try:
            cleaned.append(Webhook(**item))
        except ValidationError as exc:
            errors = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors())
            raise HTTPException(status_code=422, detail=f"Invalid webhook: {errors}") from exc
    hooks = LabSettings(db).update_webhooks(cleaned, admin.username)
    AuditService(AuditRepository(db)).record(
        action="settings.webhooks", user_id=admin.username, detail=", ".join(hook.name for hook in hooks)
    )
    return {"webhooks": _masked(hooks), "events": list(WEBHOOK_EVENTS)}


@router.post("/settings/webhooks/{webhook_id}/test")
def test_webhook(webhook_id: str, db: DB, admin=Depends(require_role("admin"))):
    hook = next((item for item in LabSettings(db).webhooks() if item.id == webhook_id), None)
    if hook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    ok = deliver(hook, "test", f"Test notification from TargetHub (sent by {admin.username})", {})
    if not ok:
        raise HTTPException(status_code=502, detail="Webhook delivery failed; check the URL and network")
    return {"delivered": True}
