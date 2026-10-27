from fastapi import APIRouter

from app.api.v1.agents import router as agents_router
from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.lab import router as lab_router
from app.api.v1.labs import router as labs_router
from app.api.v1.providers import router as providers_router
from app.api.v1.reservations import router as reservations_router
from app.api.v1.serial_ws import router as serial_ws_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.target_capabilities import router as target_capabilities_router
from app.api.v1.targets import router as targets_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(targets_router)
api_router.include_router(target_capabilities_router)
api_router.include_router(reservations_router)
api_router.include_router(sessions_router)
api_router.include_router(serial_ws_router)
api_router.include_router(providers_router)
api_router.include_router(agents_router)
api_router.include_router(auth_router)
api_router.include_router(audit_router)
api_router.include_router(labs_router)
api_router.include_router(lab_router)
