from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.auth_service import AuthError, AuthService


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


bearer = HTTPBearer(auto_error=False)


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    auth: AuthService = Depends(get_auth_service),
):
    """Authenticate a user access token (JWT) or a personal API token (thp_...)."""
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401, detail="Authorization required", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        return auth.user_for_bearer(credentials.credentials)
    except AuthError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token" if "expired" in str(exc) or "signature" in str(exc) else str(exc).capitalize(),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def resolve_principal(db: Session, token: str):
    """Return the user a bearer token belongs to, or None (no exceptions)."""
    if not token:
        return None
    try:
        return AuthService(db).user_for_bearer(token)
    except AuthError:
        return None


def require_role(role: str):
    def _dep(user=Depends(get_current_user)):
        if role not in user.role_list:
            raise HTTPException(status_code=403, detail=f"This action requires the '{role}' role")
        return user

    return _dep


def require_any_role(*roles: str):
    def _dep(user=Depends(get_current_user)):
        if not set(roles) & set(user.role_list):
            raise HTTPException(
                status_code=403, detail=f"This action requires one of the roles: {', '.join(roles)}"
            )
        return user

    return _dep


# Reserving targets and operating hardware is for users and admins, not viewers.
require_operator = require_any_role("admin", "user")


def is_admin_user(user) -> bool:
    roles = (user.roles or "").split(",") if getattr(user, "roles", None) else []
    return "admin" in roles


def resolve_effective_user_id(current_user, requested_user_id: str | None = None) -> str:
    current_username = current_user.username
    if requested_user_id is None or requested_user_id == "":
        return current_username

    if requested_user_id == current_username:
        return requested_user_id

    if is_admin_user(current_user):
        return requested_user_id

    raise HTTPException(status_code=403, detail="forbidden")
