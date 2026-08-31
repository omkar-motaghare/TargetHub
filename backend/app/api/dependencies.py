from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db.session import SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.auth_service import AuthService

bearer = HTTPBearer(auto_error=False)


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    auth: AuthService = Depends(get_auth_service),
):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authorization required")
    try:
        payload = auth.verify_token(credentials.credentials)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    username = payload.get("sub")
    user = auth.repo.get_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_role(role: str):
    def _dep(user=Depends(get_current_user)):
        roles = (user.roles or "").split(",") if user.roles else []
        if role not in roles:
            raise HTTPException(status_code=403, detail="forbidden")
        return user

    return _dep


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
