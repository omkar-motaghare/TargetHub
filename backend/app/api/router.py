from fastapi import APIRouter

from app.api.v1.reservations import router as reservations_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.targets import router as targets_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(targets_router)
api_router.include_router(reservations_router)
api_router.include_router(sessions_router)
