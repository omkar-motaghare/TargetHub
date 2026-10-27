"""Admin-editable lab policy and notification settings, stored in the database."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator
from sqlalchemy.orm import Session

from app.models.lab import AppSetting

POLICY_KEY = "reservation_policy"
WEBHOOKS_KEY = "webhooks"

WEBHOOK_EVENTS = (
    "reservation.created",
    "reservation.released",
    "reservation.expiring",
    "reservation.expired",
    "reservation.extended",
    "waitlist.fulfilled",
    "target.status",
    "agent.offline",
    "agent.online",
)


class ReservationPolicy(BaseModel):
    max_duration_minutes: int = Field(default=480, ge=5, le=60 * 24 * 31)
    max_advance_days: int = Field(default=30, ge=0, le=365)
    # 0 means unlimited. Admins are exempt from the per-user limit.
    max_active_reservations_per_user: int = Field(default=0, ge=0, le=1000)
    default_duration_minutes: int = Field(default=60, ge=5, le=60 * 24)
    expiry_warning_minutes: int = Field(default=10, ge=0, le=240)
    allow_extend_when_waitlisted: bool = False
    waitlist_entry_ttl_hours: int = Field(default=24, ge=1, le=24 * 14)
    transcript_retention_days: int = Field(default=30, ge=1, le=3650)
    audit_retention_days: int = Field(default=365, ge=7, le=3650)


class Webhook(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    format: Literal["slack", "teams", "generic"] = "generic"
    events: list[str] = Field(default_factory=lambda: list(WEBHOOK_EVENTS))
    enabled: bool = True
    # Optional HMAC secret for the X-TargetHub-Signature header (generic format).
    secret: str | None = Field(default=None, max_length=200)

    @field_validator("events")
    @classmethod
    def _known_events(cls, events: list[str]) -> list[str]:
        unknown = sorted(set(events) - set(WEBHOOK_EVENTS))
        if unknown:
            raise ValueError(f"unknown events: {', '.join(unknown)}")
        return events


class WebhookList(BaseModel):
    webhooks: list[Webhook] = Field(default_factory=list, max_length=20)


class LabSettings:
    def __init__(self, db: Session):
        self.db = db

    def _get(self, key: str) -> dict:
        row = self.db.get(AppSetting, key)
        return dict(row.value) if row and isinstance(row.value, dict) else {}

    def _put(self, key: str, value: dict, actor: str | None) -> None:
        row = self.db.get(AppSetting, key)
        if row is None:
            self.db.add(AppSetting(key=key, value=value, updated_by=actor))
        else:
            row.value = value
            row.updated_by = actor
        self.db.commit()

    def policy(self) -> ReservationPolicy:
        return ReservationPolicy(**self._get(POLICY_KEY))

    def update_policy(self, policy: ReservationPolicy, actor: str | None) -> ReservationPolicy:
        self._put(POLICY_KEY, policy.model_dump(), actor)
        return policy

    def webhooks(self) -> list[Webhook]:
        return WebhookList(**self._get(WEBHOOKS_KEY)).webhooks

    def update_webhooks(self, webhooks: list[Webhook], actor: str | None) -> list[Webhook]:
        existing = {hook.id: hook for hook in self.webhooks()}
        merged = []
        for hook in webhooks:
            # Secrets are write-only: an omitted secret keeps the stored one.
            if hook.secret is None and hook.id in existing:
                hook = hook.model_copy(update={"secret": existing[hook.id].secret})
            merged.append(hook)
        self._put(WEBHOOKS_KEY, WebhookList(webhooks=merged).model_dump(mode="json"), actor)
        return merged
