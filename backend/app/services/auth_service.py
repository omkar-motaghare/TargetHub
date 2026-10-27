"""Local-account authentication: password hashing, access/refresh tokens, API tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.tokens import ApiToken, RefreshToken
from app.db.models.user import KNOWN_ROLES, ROLE_ADMIN, User
from app.repositories.user_repository import UserRepository

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{2,99}$")
API_TOKEN_PREFIX = "thp_"
MAX_API_TOKENS_PER_USER = 20


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = -len(data) % 4
    return base64.urlsafe_b64decode(data + "=" * padding)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class AuthError(ValueError):
    """Authentication failed; message is safe to show to the caller."""


class AuthService:
    # PBKDF2-HMAC-SHA256 (OWASP 2023 guidance: 600k iterations).
    _ALG = "sha256"
    _LEGACY_ITER = 100_000

    @property
    def _ITER(self) -> int:  # noqa: N802 - kept as a constant-like name
        return settings.password_hash_iterations
    _SALT_BYTES = 16

    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepository(db)

    # ------------------------------------------------------------------ passwords

    def _hash_password(self, password: str, salt: bytes | None = None, iterations: int | None = None) -> str:
        salt = salt if salt is not None else secrets.token_bytes(self._SALT_BYTES)
        rounds = iterations or self._ITER
        dk = hashlib.pbkdf2_hmac(self._ALG, password.encode("utf-8"), salt, rounds)
        return f"pbkdf2_{self._ALG}${rounds}${salt.hex()}${dk.hex()}"

    def _verify_password(self, password: str, stored: str) -> bool:
        try:
            if stored.startswith("pbkdf2_"):
                scheme, rounds, salt_hex, dk_hex = stored.split("$", 3)
                algorithm = scheme.removeprefix("pbkdf2_")
                iterations = int(rounds)
            else:  # legacy "salt$hash" format (100k iterations)
                salt_hex, dk_hex = stored.split("$", 1)
                algorithm, iterations = self._ALG, self._LEGACY_ITER
            salt = bytes.fromhex(salt_hex)
            expected = bytes.fromhex(dk_hex)
        except (ValueError, AttributeError):
            return False
        dk = hashlib.pbkdf2_hmac(algorithm, password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(dk, expected)

    def _needs_rehash(self, stored: str) -> bool:
        return not stored.startswith(f"pbkdf2_{self._ALG}${self._ITER}$")

    @staticmethod
    def validate_password(password: str, username: str | None = None) -> None:
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        if len(password) > 256:
            raise ValueError("password must be at most 256 characters")
        if username and password.lower() == username.lower():
            raise ValueError("password must not equal the username")

    # ------------------------------------------------------------------ users

    @staticmethod
    def _normalize_roles(roles: list[str] | None) -> list[str]:
        normalized: list[str] = []
        for role in roles or []:
            role_name = role.strip().lower()
            if not role_name:
                continue
            if role_name not in KNOWN_ROLES:
                raise ValueError(f"unknown role '{role_name}' (allowed: {', '.join(KNOWN_ROLES)})")
            if role_name not in normalized:
                normalized.append(role_name)
        return normalized

    @staticmethod
    def validate_username(username: str) -> str:
        username = username.strip()
        if not USERNAME_PATTERN.match(username):
            raise ValueError(
                "username must be 3-100 characters: letters, digits, '.', '_', '-', '@' "
                "(starting with a letter or digit)"
            )
        return username

    def _get_by_username_ci(self, username: str) -> User | None:
        return self.repo.get_by_username_ci(username)

    def create_user(
        self,
        username: str,
        password: str,
        roles: list[str] | None = None,
        display_name: str | None = None,
        email: str | None = None,
    ) -> User:
        username = self.validate_username(username)
        roles = self._normalize_roles(roles) or ["user"]
        if self._get_by_username_ci(username):
            raise ValueError("username already exists")
        self.validate_password(password, username)
        user = User(
            username=username,
            password_hash=self._hash_password(password),
            roles=",".join(roles),
            display_name=display_name,
            email=email,
            is_active=True,
            token_version=0,
            created_at=datetime.now(UTC),
        )
        return self.repo.create(user)

    def list_users(self) -> list[User]:
        return self.repo.list()

    def _other_active_admins(self, user_id: int) -> int:
        return sum(
            1
            for existing in self.repo.list()
            if ROLE_ADMIN in existing.role_list and existing.id != user_id and existing.is_active
        )

    def update_user(
        self,
        user_id: int,
        roles: list[str] | None = None,
        password: str | None = None,
        is_active: bool | None = None,
        display_name: str | None = None,
        email: str | None = None,
    ) -> User:
        user = self.repo.get_by_id(user_id)
        if not user:
            raise ValueError("user not found")
        is_admin_now = ROLE_ADMIN in user.role_list and user.is_active
        if roles is not None:
            updated_roles = self._normalize_roles(roles)
            if not updated_roles:
                raise ValueError("a user needs at least one role")
            if is_admin_now and ROLE_ADMIN not in updated_roles and self._other_active_admins(user_id) == 0:
                raise ValueError("cannot remove admin role from the last admin user")
            user.roles = ",".join(updated_roles)
        if is_active is not None and is_active != user.is_active:
            if not is_active and is_admin_now and self._other_active_admins(user_id) == 0:
                raise ValueError("cannot disable the last admin user")
            user.is_active = is_active
            if not is_active:
                self._invalidate_all_tokens(user)
        if password is not None:
            self.validate_password(password, user.username)
            user.password_hash = self._hash_password(password)
            self._invalidate_all_tokens(user)
        if display_name is not None:
            user.display_name = display_name or None
        if email is not None:
            user.email = email or None
        return self.repo.save(user)

    def delete_user(self, user_id: int) -> None:
        user = self.repo.get_by_id(user_id)
        if not user:
            raise ValueError("user not found")
        if ROLE_ADMIN in user.role_list and user.is_active and self._other_active_admins(user_id) == 0:
            raise ValueError("cannot delete the last admin user")
        self.repo.delete(user)

    def change_own_password(self, username: str, current_password: str, new_password: str) -> User:
        """Self-service password change. Verifies the caller's current password first."""
        user = self.repo.get_by_username(username)
        if not user or not user.is_active or not self._verify_password(current_password, user.password_hash or ""):
            raise AuthError("incorrect username or current password")
        self.validate_password(new_password, user.username)
        user.password_hash = self._hash_password(new_password)
        self._invalidate_all_tokens(user)
        return self.repo.save(user)

    def authenticate(self, username: str, password: str) -> User | None:
        user = self.repo.get_by_username(username)
        if not user or not user.is_active:
            # Equalize timing a little for unknown users.
            self._verify_password(password, self._hash_password("x", b"0" * 16))
            return None
        if not self._verify_password(password, user.password_hash or ""):
            return None
        if self._needs_rehash(user.password_hash or ""):
            user.password_hash = self._hash_password(password)
        user.last_login_at = datetime.now(UTC)
        self.repo.save(user)
        return user

    def can_bootstrap(self) -> bool:
        """Bootstrap is only available before any user account exists."""
        return self.repo.count() == 0

    def bootstrap_admin(self, username: str, password: str) -> User:
        if not self.can_bootstrap():
            raise ValueError("admin bootstrap has already been completed")
        return self.create_user(username, password, [ROLE_ADMIN])

    # ------------------------------------------------------------------ access tokens (JWT HS256)

    def _sign(self, signing_input: bytes) -> bytes:
        return hmac.new(settings.secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()

    def create_access_token(
        self,
        username: str,
        roles: list[str],
        expires_minutes: int | None = None,
        version: int = 0,
    ) -> str:
        minutes = settings.access_token_minutes if expires_minutes is None else expires_minutes
        header = {"alg": "HS256", "typ": "JWT"}
        now = int(time.time())
        payload = {
            "sub": username,
            "roles": roles,
            "ver": version,
            "typ": "access",
            "iat": now,
            "exp": now + int(minutes * 60),
        }
        segments = [
            _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
        segments.append(_b64url_encode(self._sign(".".join(segments).encode("ascii"))))
        return ".".join(segments)

    def verify_token(self, token: str) -> dict[str, Any]:
        try:
            header_b64, payload_b64, sig_b64 = token.split(".")
            signature = _b64url_decode(sig_b64)
        except ValueError as exc:
            raise AuthError("invalid token") from exc
        if not hmac.compare_digest(signature, self._sign(f"{header_b64}.{payload_b64}".encode("ascii"))):
            raise AuthError("invalid signature")
        try:
            header = json.loads(_b64url_decode(header_b64))
            payload = json.loads(_b64url_decode(payload_b64))
        except (ValueError, UnicodeDecodeError) as exc:
            raise AuthError("invalid token") from exc
        if header.get("alg") != "HS256":
            raise AuthError("unsupported token algorithm")
        if payload.get("typ", "access") != "access":
            raise AuthError("not an access token")
        if int(payload.get("exp", 0)) < int(time.time()):
            raise AuthError("token expired")
        return payload

    def user_for_access_token(self, token: str) -> User:
        payload = self.verify_token(token)
        user = self.repo.get_by_username(payload.get("sub", ""))
        if not user:
            raise AuthError("user not found")
        if not user.is_active:
            raise AuthError("user is disabled")
        if int(payload.get("ver", 0)) != int(user.token_version or 0):
            raise AuthError("token has been revoked")
        return user

    def access_token_for(self, user: User) -> str:
        return self.create_access_token(user.username, user.role_list, version=int(user.token_version or 0))

    # ------------------------------------------------------------------ refresh tokens

    @staticmethod
    def _digest(value: str) -> str:
        return hmac.new(settings.secret_key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()

    def issue_refresh_token(self, user: User, family_id: str | None = None, user_agent: str | None = None) -> str:
        token = f"thr_{secrets.token_urlsafe(32)}"
        self.db.add(
            RefreshToken(
                user_id=user.id,
                family_id=family_id or str(uuid.uuid4()),
                token_hash=self._digest(token),
                expires_at=datetime.now(UTC) + timedelta(hours=settings.refresh_token_hours),
                user_agent=(user_agent or "")[:200] or None,
            )
        )
        self.db.commit()
        return token

    def token_pair(self, user: User, user_agent: str | None = None) -> dict[str, Any]:
        return {
            "access_token": self.access_token_for(user),
            "refresh_token": self.issue_refresh_token(user, user_agent=user_agent),
            "token_type": "bearer",
            "expires_in": settings.access_token_minutes * 60,
        }

    def refresh(self, refresh_token: str, user_agent: str | None = None) -> dict[str, Any]:
        """Rotate a refresh token. Presenting an already-rotated token revokes its family."""
        record = self.db.scalar(select(RefreshToken).where(RefreshToken.token_hash == self._digest(refresh_token)))
        now = datetime.now(UTC)
        if record is None:
            raise AuthError("invalid refresh token")
        if record.revoked_at is not None or record.used_at is not None:
            self._revoke_family(record.family_id, now)
            raise AuthError("refresh token has already been used or revoked")
        if _as_utc(record.expires_at) <= now:
            raise AuthError("refresh token expired")
        user = self.repo.get_by_id(record.user_id)
        if user is None or not user.is_active:
            raise AuthError("user is disabled")
        # Conditional update so two concurrent refreshes cannot both rotate.
        claimed = self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.id == record.id, RefreshToken.used_at.is_(None), RefreshToken.revoked_at.is_(None))
            .values(used_at=now)
        ).rowcount
        self.db.commit()
        if claimed != 1:
            self._revoke_family(record.family_id, now)
            raise AuthError("refresh token has already been used or revoked")
        return {
            "access_token": self.access_token_for(user),
            "refresh_token": self.issue_refresh_token(user, family_id=record.family_id, user_agent=user_agent),
            "token_type": "bearer",
            "expires_in": settings.access_token_minutes * 60,
        }

    def _revoke_family(self, family_id: str, now: datetime) -> None:
        self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        self.db.commit()

    def logout(self, refresh_token: str) -> None:
        record = self.db.scalar(select(RefreshToken).where(RefreshToken.token_hash == self._digest(refresh_token)))
        if record is not None:
            self._revoke_family(record.family_id, datetime.now(UTC))

    def _invalidate_all_tokens(self, user: User) -> None:
        """Revoke every access and refresh token (API tokens are managed separately)."""
        user.token_version = int(user.token_version or 0) + 1
        self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )

    def logout_everywhere(self, user: User) -> None:
        self._invalidate_all_tokens(user)
        self.repo.save(user)

    # ------------------------------------------------------------------ API tokens

    def create_api_token(self, user: User, name: str, expires_days: int | None = None) -> tuple[ApiToken, str]:
        name = name.strip()
        if not name:
            raise ValueError("token name is required")
        active = [item for item in self.list_api_tokens(user) if item.revoked_at is None]
        if len(active) >= MAX_API_TOKENS_PER_USER:
            raise ValueError(f"at most {MAX_API_TOKENS_PER_USER} active API tokens per user")
        token = f"{API_TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
        record = ApiToken(
            user_id=user.id,
            name=name[:100],
            token_hash=self._digest(token),
            prefix=token[:12],
            expires_at=(datetime.now(UTC) + timedelta(days=expires_days)) if expires_days else None,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record, token

    def list_api_tokens(self, user: User) -> list[ApiToken]:
        return list(
            self.db.scalars(
                select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc())
            ).all()
        )

    def revoke_api_token(self, user: User, token_id: str, *, as_admin: bool = False) -> ApiToken:
        record = self.db.get(ApiToken, token_id)
        if record is None or (record.user_id != user.id and not as_admin):
            raise ValueError("token not found")
        if record.revoked_at is None:
            record.revoked_at = datetime.now(UTC)
            self.db.commit()
        return record

    def user_for_api_token(self, token: str) -> User:
        record = self.db.scalar(select(ApiToken).where(ApiToken.token_hash == self._digest(token)))
        now = datetime.now(UTC)
        if record is None or record.revoked_at is not None:
            raise AuthError("invalid API token")
        if record.expires_at is not None and _as_utc(record.expires_at) <= now:
            raise AuthError("API token expired")
        user = self.repo.get_by_id(record.user_id)
        if user is None or not user.is_active:
            raise AuthError("user is disabled")
        last_used = _as_utc(record.last_used_at)
        if last_used is None or now - last_used > timedelta(minutes=1):
            record.last_used_at = now
            self.db.commit()
        return user

    # ------------------------------------------------------------------ any bearer

    def user_for_bearer(self, token: str) -> User:
        if token.startswith(API_TOKEN_PREFIX):
            return self.user_for_api_token(token)
        return self.user_for_access_token(token)
