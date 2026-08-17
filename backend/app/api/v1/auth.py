from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.schemas.user import Token, UserCreate, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


def get_auth_service(db: Annotated[Session, Depends(get_db)]) -> AuthService:
    return AuthService(db)


@router.post("/token", response_model=Token)
def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    auth: AuthService = Depends(get_auth_service),
):
    user = auth.authenticate(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    roles = (user.roles or "").split(",") if user.roles else []
    token = auth.create_access_token(user.username, roles)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/users", response_model=UserResponse)
def create_user(request: UserCreate, auth: AuthService = Depends(get_auth_service)):
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
