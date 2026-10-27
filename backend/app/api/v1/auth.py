import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db, is_admin_user, require_role
from app.core.config import settings
from app.core.rate_limit import enforce_auth_limit, record_auth_failure, record_auth_success
from app.repositories.audit_repository import AuditRepository
from app.schemas.user import (
    AdminBootstrapRequest,
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenResponse,
    ChangePasswordRequest,
    RefreshRequest,
    Token,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.services.audit_service import AuditService
from app.services.auth_service import AuthError, AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


def get_auth_service(db: Annotated[Session, Depends(get_db)]) -> AuthService:
    return AuthService(db)


def get_audit(db: Annotated[Session, Depends(get_db)]) -> AuditService:
    return AuditService(AuditRepository(db))


Audit = Annotated[AuditService, Depends(get_audit)]


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


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
    audit: Audit,
    auth: AuthService = Depends(get_auth_service),
):
    """Password login. Returns a short-lived access token and a rotating refresh token."""
    client_ip = _client_ip(request)
    enforce_auth_limit(client_ip, form_data.username, settings.auth_max_failures, settings.auth_failure_window_seconds)
    user = auth.authenticate(form_data.username, form_data.password)
    if not user:
        record_auth_failure(client_ip, form_data.username)
        audit.record(action="auth.login_failed", user_id=form_data.username[:100], success=False, detail=f"from {client_ip}")
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    record_auth_success(client_ip, form_data.username)
    audit.record(action="auth.login", user_id=user.username, detail=f"from {client_ip}")
    return auth.token_pair(user, user_agent=request.headers.get("user-agent"))


@router.post("/refresh", response_model=Token)
def refresh_access_token(
    request: Request,
    body: RefreshRequest,
    auth: AuthService = Depends(get_auth_service),
):
    """Exchange a refresh token for a new access + refresh token pair (rotation)."""
    client_ip = _client_ip(request)
    enforce_auth_limit(client_ip, "refresh", settings.auth_max_failures * 4, settings.auth_failure_window_seconds)
    try:
        return auth.refresh(body.refresh_token, user_agent=request.headers.get("user-agent"))
    except AuthError as exc:
        record_auth_failure(client_ip, "refresh")
        raise HTTPException(status_code=401, detail=str(exc).capitalize()) from exc


@router.post("/logout", status_code=204)
def logout(body: RefreshRequest, auth: AuthService = Depends(get_auth_service)):
    """Revoke a refresh token (and the rotation family it belongs to)."""
    auth.logout(body.refresh_token)


@router.post("/logout-all", status_code=204)
def logout_everywhere(audit: Audit, user=Depends(get_current_user), auth: AuthService = Depends(get_auth_service)):
    """Invalidate every access and refresh token of the caller (API tokens are kept)."""
    auth.logout_everywhere(auth.repo.get_by_id(user.id))
    audit.record(action="auth.logout_all", user_id=user.username)


@router.post("/change-password", status_code=204)
def change_password(
    http_request: Request,
    request: ChangePasswordRequest,
    audit: Audit,
    auth: AuthService = Depends(get_auth_service),
):
    """Self-service password change for any user. Requires the current password;
    does not require an active session, so it also works from the login screen.
    All existing logins of the user are signed out."""
    client_ip = _client_ip(http_request)
    enforce_auth_limit(client_ip, request.username, settings.auth_max_failures, settings.auth_failure_window_seconds)
    try:
        auth.change_own_password(request.username, request.current_password, request.new_password)
    except AuthError:
        record_auth_failure(client_ip, request.username)
        raise HTTPException(status_code=401, detail="Incorrect username or current password") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_auth_success(client_ip, request.username)
    audit.record(action="auth.password_change", user_id=request.username)


@router.post("/bootstrap", response_model=UserResponse, status_code=201)
def bootstrap_admin(
    http_request: Request,
    request: AdminBootstrapRequest,
    audit: Audit,
    auth: AuthService = Depends(get_auth_service),
):
    """Create the first admin account. Disabled unless ADMIN_BOOTSTRAP_TOKEN is set."""
    expected_token = settings.admin_bootstrap_token
    if not expected_token:
        raise HTTPException(
            status_code=403,
            detail="Admin bootstrap is disabled. Set ADMIN_BOOTSTRAP_TOKEN to enable it.",
        )
    client_ip = _client_ip(http_request)
    enforce_auth_limit(client_ip, "bootstrap", settings.auth_max_failures, settings.auth_failure_window_seconds)
    if not hmac.compare_digest(request.bootstrap_token, expected_token):
        record_auth_failure(client_ip, "bootstrap")
        raise HTTPException(status_code=401, detail="Invalid bootstrap token")
    if not auth.can_bootstrap():
        raise HTTPException(status_code=409, detail="admin bootstrap has already been completed")
    try:
        user = auth.bootstrap_admin(request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record(action="auth.bootstrap", user_id=user.username)
    return UserResponse.of(user)


# --------------------------------------------------------------------------- users (admin)


@router.post("/users", response_model=UserResponse)
def create_user(
    request: UserCreate,
    audit: Audit,
    auth: AuthService = Depends(get_auth_service),
    admin=Depends(require_role("admin")),
):
    try:
        user = auth.create_user(request.username, request.password, request.roles, request.display_name, request.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record(action="user.create", user_id=admin.username, detail=f"{user.username} roles={user.roles}")
    return UserResponse.of(user)


@router.get("/users", response_model=list[UserResponse])
def list_users(
    auth: AuthService = Depends(get_auth_service),
    _admin=Depends(require_role("admin")),
):
    return [UserResponse.of(user) for user in auth.list_users()]


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    request: UserUpdate,
    audit: Audit,
    auth: AuthService = Depends(get_auth_service),
    admin=Depends(require_role("admin")),
):
    try:
        user = auth.update_user(
            user_id=user_id,
            roles=request.roles,
            password=request.password,
            is_active=request.is_active,
            display_name=request.display_name,
            email=request.email,
        )
    except ValueError as exc:
        message = str(exc)
        if message == "user not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    changes = ", ".join(key for key, value in request.model_dump(exclude_unset=True).items() if key != "password")
    if request.password is not None:
        changes = f"{changes}, password" if changes else "password"
    audit.record(action="user.update", user_id=admin.username, detail=f"{user.username}: {changes}")
    return UserResponse.of(user)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    audit: Audit,
    auth: AuthService = Depends(get_auth_service),
    admin=Depends(require_role("admin")),
):
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="cannot delete currently authenticated user")
    target = auth.repo.get_by_id(user_id)
    try:
        auth.delete_user(user_id)
    except ValueError as exc:
        message = str(exc)
        if message == "user not found":
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    audit.record(action="user.delete", user_id=admin.username, detail=target.username if target else str(user_id))


@router.get("/me", response_model=UserResponse)
def get_me(user=Depends(get_current_user)):
    return UserResponse.of(user)


# --------------------------------------------------------------------------- personal API tokens


@router.get("/api-tokens", response_model=list[ApiTokenResponse])
def list_api_tokens(user=Depends(get_current_user), auth: AuthService = Depends(get_auth_service)):
    return auth.list_api_tokens(user)


@router.post("/api-tokens", response_model=ApiTokenCreated, status_code=201)
def create_api_token(
    request: ApiTokenCreate,
    audit: Audit,
    user=Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
):
    """Create a personal token for the CLI, SDK, VS Code or CI. It acts with your roles."""
    try:
        record, token = auth.create_api_token(user, request.name, request.expires_days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record(action="api_token.create", user_id=user.username, detail=f"{record.name} ({record.prefix})")
    return ApiTokenCreated(**ApiTokenResponse.model_validate(record).model_dump(), token=token)


@router.delete("/api-tokens/{token_id}", status_code=204)
def revoke_api_token(
    token_id: str,
    audit: Audit,
    user=Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
):
    try:
        record = auth.revoke_api_token(user, token_id, as_admin=is_admin_user(user))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    audit.record(action="api_token.revoke", user_id=user.username, detail=f"{record.name} ({record.prefix})")
