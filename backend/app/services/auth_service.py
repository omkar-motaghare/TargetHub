import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.user import User
from app.repositories.user_repository import UserRepository


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = -len(data) % 4
    return base64.urlsafe_b64decode(data + "=" * padding)


class AuthService:
    # PBKDF2 settings
    _ITER = 100_000
    _ALG = "sha256"
    _SALT_BYTES = 16

    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepository(db)

    def _hash_password(self, password: str, salt: bytes | None = None) -> str:
        if salt is None:
            salt = secrets.token_bytes(self._SALT_BYTES)
        dk = hashlib.pbkdf2_hmac(self._ALG, password.encode("utf-8"), salt, self._ITER)
        return f"{salt.hex()}${dk.hex()}"

    def _verify_password(self, password: str, stored: str) -> bool:
        try:
            salt_hex, dk_hex = stored.split("$", 1)
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(dk_hex)
        except Exception:
            return False
        dk = hashlib.pbkdf2_hmac(self._ALG, password.encode("utf-8"), salt, self._ITER)
        return hmac.compare_digest(dk, expected)

    @staticmethod
    def _normalize_roles(roles: list[str] | None) -> list[str]:
        normalized: list[str] = []
        for role in roles or []:
            role_name = role.strip()
            if role_name and role_name not in normalized:
                normalized.append(role_name)
        return normalized

    def create_user(self, username: str, password: str, roles: list[str] | None = None) -> User:
        roles = self._normalize_roles(roles)
        existing = self.repo.get_by_username(username)
        if existing:
            raise ValueError("username already exists")
        u = User()
        u.username = username
        u.password_hash = self._hash_password(password)
        u.roles = ",".join(roles)
        u.created_at = datetime.now(UTC)
        return self.repo.create(u)

    def list_users(self) -> list[User]:
        return self.repo.list()

    def update_user(self, user_id: int, roles: list[str] | None = None, password: str | None = None) -> User:
        user = self.repo.get_by_id(user_id)
        if not user:
            raise ValueError("user not found")
        if roles is not None:
            updated_roles = self._normalize_roles(roles)
            had_admin = "admin" in ((user.roles or "").split(",") if user.roles else [])
            has_admin = "admin" in updated_roles
            if had_admin and not has_admin:
                admins_remaining = sum(
                    1
                    for existing in self.repo.list()
                    if "admin" in ((existing.roles or "").split(",") if existing.roles else []) and existing.id != user_id
                )
                if admins_remaining == 0:
                    raise ValueError("cannot remove admin role from the last admin user")
            user.roles = ",".join(updated_roles)
        if password is not None:
            user.password_hash = self._hash_password(password)
        return self.repo.save(user)

    def delete_user(self, user_id: int) -> None:
        user = self.repo.get_by_id(user_id)
        if not user:
            raise ValueError("user not found")
        user_roles = (user.roles or "").split(",") if user.roles else []
        if "admin" in user_roles:
            admins_remaining = sum(
                1
                for existing in self.repo.list()
                if "admin" in ((existing.roles or "").split(",") if existing.roles else []) and existing.id != user_id
            )
            if admins_remaining == 0:
                raise ValueError("cannot delete the last admin user")
        self.repo.delete(user)

    def change_own_password(self, username: str, current_password: str, new_password: str) -> User:
        """Self-service password change. Verifies the caller's current password first."""
        user = self.repo.get_by_username(username)
        if not user or not self._verify_password(current_password, user.password_hash or ""):
            raise ValueError("incorrect username or current password")
        user.password_hash = self._hash_password(new_password)
        return self.repo.save(user)

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.repo.get_by_username(username)
        if not user:
            return None
        if not self._verify_password(password, user.password_hash or ""):
            return None
        return user

    def can_bootstrap(self) -> bool:
        """Bootstrap is only available before any user account exists."""
        return self.repo.count() == 0

    def bootstrap_admin(self, username: str, password: str) -> User:
        if not self.can_bootstrap():
            raise ValueError("admin bootstrap has already been completed")
        user = User()
        user.username = username
        user.password_hash = self._hash_password(password)
        user.roles = "admin"
        user.created_at = datetime.now(UTC)
        return self.repo.create(user)

    # Minimal JWT implementation (HS256)
    def create_access_token(self, username: str, roles: list[str], expires_minutes: int = 15) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        now = int(time.time())
        payload = {
            "sub": username,
            "roles": roles,
            "iat": now,
            "exp": now + int(expires_minutes * 60),
        }
        segments = []
        segments.append(_b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")))
        segments.append(_b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")))
        signing_input = ".".join(segments).encode("ascii")
        sig = hmac.new(settings.secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
        segments.append(_b64url_encode(sig))
        return ".".join(segments)

    def verify_token(self, token: str) -> dict[str, Any]:
        try:
            header_b64, payload_b64, sig_b64 = token.split(".")
        except ValueError:
            raise ValueError("invalid token")
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        sig = _b64url_decode(sig_b64)
        expected = hmac.new(settings.secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("invalid signature")
        payload = json.loads(_b64url_decode(payload_b64))
        now = int(time.time())
        if payload.get("exp", 0) < now:
            raise ValueError("token expired")
        return payload
