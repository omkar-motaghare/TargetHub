from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

from app.core.exceptions import ConflictResource, ResourceNotFound
from app.providers.serial import SerialProvider, SerialProviderConfig
from app.repositories.session_repository import SessionRepository


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _env_prefix(provider_key: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", provider_key).strip("_").upper()
    return f"TARGETHUB_{normalized}"


class ProviderGateway:
    """Session-gated dispatch for provider operations.

    This is a prototype in-process gateway. It keeps provider instances in
    memory per session so open/read/write/close can share the same connection.
    """

    _serial_providers: dict[str, SerialProvider] = {}

    def __init__(self, session_repository: SessionRepository):
        self.session_repository = session_repository

    def _get_active_session(self, session_id: str, user_id: str):
        now = datetime.now(timezone.utc)
        self.session_repository.expire_due(now)

        session = self.session_repository.get(session_id)
        if session is None:
            raise ResourceNotFound("Session", session_id)
        if session.user_id != user_id:
            raise ConflictResource("Only the session owner can perform provider operations")
        if session.status != "active":
            raise ConflictResource(f"Session '{session_id}' is {session.status}")
        if _as_utc(session.expires_at) <= now:
            raise ConflictResource("Session has expired")
        if not session.provider_key:
            raise ConflictResource("Session has no provider binding")
        if session.capability_type != "serial":
            raise ConflictResource(
                f"Capability type '{session.capability_type}' is not supported by this endpoint"
            )

        return session

    def _build_serial_provider(self, provider_key: str) -> SerialProvider:
        prefix = _env_prefix(provider_key)
        port = os.getenv(f"{prefix}_PORT")
        if not port:
            raise ConflictResource(f"Serial provider '{provider_key}' is not configured")

        try:
            baudrate = int(os.getenv(f"{prefix}_BAUDRATE", "115200"))
            timeout = float(os.getenv(f"{prefix}_TIMEOUT", "0.2"))
        except ValueError as exc:
            raise ConflictResource("Invalid serial provider configuration") from exc

        return SerialProvider(
            SerialProviderConfig(
                provider_key=provider_key,
                port=port,
                baudrate=baudrate,
                timeout=timeout,
            )
        )

    def _ensure_open_serial_provider(self, session_id: str, provider_key: str) -> SerialProvider:
        provider = self._serial_providers.get(session_id)
        if provider is None:
            provider = self._build_serial_provider(provider_key)
            open_result = provider.open()
            if not open_result.success:
                raise ConflictResource(open_result.message)
            self._serial_providers[session_id] = provider
        return provider

    @staticmethod
    def _normalize_serial_data(data: dict[str, Any] | None) -> dict[str, Any] | None:
        if not data or "data" not in data:
            return data

        payload = dict(data)
        raw = payload.get("data")
        if isinstance(raw, bytes):
            payload["data_hex"] = raw.hex()
            payload["data_text"] = raw.decode("utf-8", errors="replace")
            payload["data"] = payload["data_text"]
        return payload

    def serial_open(self, session_id: str, user_id: str):
        session = self._get_active_session(session_id, user_id)
        provider = self._ensure_open_serial_provider(session_id, session.provider_key)
        result = provider.health_check()
        if not result.success:
            raise ConflictResource(result.message)
        return {
            "session_id": session_id,
            "provider_key": session.provider_key,
            "status": "open",
            "provider": result.data or {},
        }

    def serial_read(self, session_id: str, user_id: str, size: int = 4096):
        session = self._get_active_session(session_id, user_id)
        provider = self._ensure_open_serial_provider(session_id, session.provider_key)
        result = provider.read(size=size)
        if not result.success:
            raise ConflictResource(result.message)

        return {
            "session_id": session_id,
            "provider_key": session.provider_key,
            "message": result.message,
            "data": self._normalize_serial_data(result.data),
        }

    def serial_write(self, session_id: str, user_id: str, text: str):
        session = self._get_active_session(session_id, user_id)
        provider = self._ensure_open_serial_provider(session_id, session.provider_key)
        result = provider.write(text.encode("utf-8"))
        if not result.success:
            raise ConflictResource(result.message)

        return {
            "session_id": session_id,
            "provider_key": session.provider_key,
            "message": result.message,
            "data": result.data or {},
        }

    def serial_close(self, session_id: str, user_id: str):
        session = self._get_active_session(session_id, user_id)
        provider = self._serial_providers.pop(session_id, None)
        if provider is None:
            return {
                "session_id": session_id,
                "provider_key": session.provider_key,
                "status": "closed",
                "message": "Serial connection already closed",
            }

        result = provider.close()
        if not result.success:
            raise ConflictResource(result.message)
        return {
            "session_id": session_id,
            "provider_key": session.provider_key,
            "status": "closed",
            "message": result.message,
        }
