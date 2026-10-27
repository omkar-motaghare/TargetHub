import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, require_role
from app.core.config import settings
from app.core.rate_limit import enforce_auth_limit, record_auth_failure, record_auth_success
from app.schemas.user import (
    AdminBootstrapRequest,
    ChangePasswordRequest,
    Token,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


def get_auth_service(db: Annotated[Session, Depends(get_db)]) -> AuthService:
    return AuthService(db)


@router.get("/setup-status")
def setup_status(auth: AuthService = Depends(get_auth_service)):
    """Public, secret-free first-run probe: does the instance still need its first admin?"""
    return {
        "setup_required": auth.can_bootstrap(),
        "bootstrap_enabled": bool(settings.admin_bootstrap_token),
    }


@router.post("/token", response_model=Token)
def login_for_access_token(
    request: Request,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    auth: AuthService = Depends(get_auth_service),
):
    client_ip = request.client.host if request.client else None
    enforce_auth_limit(client_ip, form_data.username, settings.auth_max_failures, settings.auth_failure_window_seconds)
    user = auth.authenticate(form_data.username, form_data.password)
    if not user:
        record_auth_failure(client_ip, form_data.username)
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    record_auth_success(client_ip, form_data.username)
    roles = (user.roles or "").split(",") if user.roles else []
    token = auth.create_access_token(user.username, roles)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/change-password", status_code=204)
def change_password(
    http_request: Request,
    request: ChangePasswordRequest,
    auth: AuthService = Depends(get_auth_service),
):
    """Self-service password change for any user. Requires the current password;
    does not require an active session, so it also works from the login screen."""
    client_ip = http_request.client.host if http_request.client else None
    enforce_auth_limit(client_ip, request.username, settings.auth_max_failures, settings.auth_failure_window_seconds)
    try:
        auth.change_own_password(request.username, request.current_password, request.new_password)
    except ValueError:
        record_auth_failure(client_ip, request.username)
        raise HTTPException(status_code=401, detail="Incorrect username or current password")
    record_auth_success(client_ip, request.username)


@router.post("/bootstrap", response_model=UserResponse, status_code=201)
def bootstrap_admin(
    http_request: Request,
    request: AdminBootstrapRequest,
    auth: AuthService = Depends(get_auth_service),
):
    """Create the first admin account. Disabled unless ADMIN_BOOTSTRAP_TOKEN is set."""
    expected_token = settings.admin_bootstrap_token
    if not expected_token:
        raise HTTPException(
            status_code=403,
            detail="Admin bootstrap is disabled. Set ADMIN_BOOTSTRAP_TOKEN to enable it.",
        )
    client_ip = http_request.client.host if http_request.client else None
    enforce_auth_limit(client_ip, "bootstrap", settings.auth_max_failures, settings.auth_failure_window_seconds)
    if not hmac.compare_digest(request.bootstrap_token, expected_token):
        record_auth_failure(client_ip, "bootstrap")
        raise HTTPException(status_code=401, detail="Invalid bootstrap token")
    try:
        user = auth.bootstrap_admin(request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    roles_list = (user.roles or "").split(",") if user.roles else []
    return UserResponse(
        id=user.id,
        username=user.username,
        roles=roles_list,
        created_at=user.created_at,
    )


@router.post("/users", response_model=UserResponse)
def create_user(
    request: UserCreate,
    auth: AuthService = Depends(get_auth_service),
    _admin=Depends(require_role("admin")),
):
    try:
        user = auth.create_user(request.username, request.password, request.roles)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Convert stored CSV roles to list for response model
    roles_list = (user.roles or "").split(",") if user.roles else []
    return UserResponse(
        id=user.id,
        username=user.username,
        roles=roles_list,
        created_at=user.created_at,
    )


@router.get("/users", response_model=list[UserResponse])
def list_users(
    auth: AuthService = Depends(get_auth_service),
    _admin=Depends(require_role("admin")),
):
    users = auth.list_users()
    return [
        UserResponse(
            id=user.id,
            username=user.username,
            roles=(user.roles or "").split(",") if user.roles else [],
            created_at=user.created_at,
        )
        for user in users
    ]


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    request: UserUpdate,
    auth: AuthService = Depends(get_auth_service),
    _admin=Depends(require_role("admin")),
):
    try:
        user = auth.update_user(
            user_id=user_id,
            roles=request.roles,
            password=request.password,
        )
    except ValueError as exc:
        message = str(exc)
        if message == "user not found":
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=400, detail=message)

    return UserResponse(
        id=user.id,
        username=user.username,
        roles=(user.roles or "").split(",") if user.roles else [],
        created_at=user.created_at,
    )


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    auth: AuthService = Depends(get_auth_service),
    current_user=Depends(get_current_user),
    _admin=Depends(require_role("admin")),
):
    if current_user.id == user_id:
        raise HTTPException(status_code=400, detail="cannot delete currently authenticated user")
    try:
        auth.delete_user(user_id)
    except ValueError as exc:
        message = str(exc)
        if message == "user not found":
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=400, detail=message)


@router.get("/me", response_model=UserResponse)
def get_me(user=Depends(get_current_user)):
    roles_list = (user.roles or "").split(",") if user.roles else []
    return UserResponse(
        id=user.id,
        username=user.username,
        roles=roles_list,
        created_at=user.created_at,
    )
