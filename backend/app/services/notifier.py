"""In-app notifications and outbound webhooks (Slack, Microsoft Teams, generic JSON)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.core.metrics import metrics
from app.models.lab import Notification
from app.services.lab_settings import LabSettings, Webhook

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="webhook")
WEBHOOK_TIMEOUT_SECONDS = 5
WEBHOOK_ATTEMPTS = 3


def _body(hook: Webhook, event: str, message: str, data: dict) -> tuple[bytes, dict[str, str]]:
    link = settings.targethub_public_url.rstrip("/") + "/app"
    if hook.format == "slack":
        payload = {"text": f"*TargetHub* — {message}\n<{link}|Open TargetHub>"}
    elif hook.format == "teams":
        payload = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": message,
            "title": "TargetHub",
            "text": message,
            "potentialAction": [
                {"@type": "OpenUri", "name": "Open TargetHub", "targets": [{"os": "default", "uri": link}]}
            ],
        }
    else:
        payload = {
            "event": event,
            "message": message,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
            "instance": settings.targethub_public_url,
        }
    raw = json.dumps(payload, default=str).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": f"TargetHub/{settings.app_version}"}
    if hook.format == "generic" and hook.secret:
        signature = hmac.new(hook.secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        headers["X-TargetHub-Signature"] = f"sha256={signature}"
        headers["X-TargetHub-Event"] = event
    return raw, headers


def deliver(hook: Webhook, event: str, message: str, data: dict) -> bool:
    raw, headers = _body(hook, event, message, data)
    for attempt in range(1, WEBHOOK_ATTEMPTS + 1):
        request = urllib.request.Request(str(hook.url), data=raw, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=WEBHOOK_TIMEOUT_SECONDS) as response:
                if 200 <= response.status < 300:
                    metrics.inc("targethub_webhook_deliveries_total", labels={"result": "ok"})
                    return True
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.warning(f"webhook '{hook.name}' attempt {attempt} failed: {exc}")
        time.sleep(min(2 ** attempt, 8) * 0.25)
    metrics.inc("targethub_webhook_deliveries_total", labels={"result": "failed"})
    return False


class Notifier:
    def __init__(self, db: Session):
        self.db = db

    def notify_user(
        self,
        user_id: str,
        kind: str,
        message: str,
        *,
        target_id: str | None = None,
        reservation_id: str | None = None,
    ) -> None:
        self.db.add(
            Notification(
                user_id=user_id, kind=kind, message=message, target_id=target_id, reservation_id=reservation_id
            )
        )
        self.db.commit()

    def broadcast(self, event: str, message: str, data: dict | None = None) -> int:
        """Send an event to every enabled webhook subscribed to it (non-blocking)."""
        try:
            hooks = [hook for hook in LabSettings(self.db).webhooks() if hook.enabled and event in hook.events]
        except Exception as exc:  # pragma: no cover - settings corruption must not break callers
            logger.warning(f"cannot load webhooks: {exc}")
            return 0
        for hook in hooks:
            _executor.submit(deliver, hook, event, message, data or {})
        return len(hooks)

    def event(
        self,
        event: str,
        message: str,
        *,
        user_id: str | None = None,
        data: dict | None = None,
        target_id: str | None = None,
        reservation_id: str | None = None,
    ) -> None:
        """In-app notification for ``user_id`` (if given) plus webhook broadcast."""
        try:
            if user_id:
                self.notify_user(user_id, event, message, target_id=target_id, reservation_id=reservation_id)
            self.broadcast(event, message, data)
        except Exception as exc:  # pragma: no cover - notifications are best effort
            logger.warning(f"notification '{event}' failed: {exc}")

    # ---------------------------------------------------------------- inbox

    def list_for(self, user_id: str, unread_only: bool = False, limit: int = 50) -> list[Notification]:
        statement = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            statement = statement.where(Notification.read_at.is_(None))
        statement = statement.order_by(Notification.created_at.desc()).limit(limit)
        return list(self.db.scalars(statement).all())

    def mark_read(self, user_id: str, notification_id: str | None = None) -> int:
        statement = update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None))
        if notification_id:
            statement = statement.where(Notification.id == notification_id)
        result = self.db.execute(statement.values(read_at=datetime.now(UTC)))
        self.db.commit()
        return result.rowcount or 0
