from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import TargetHubException
from app.core.handlers import targethub_exception_handler
from app.core.logging import logger
from app.core.middleware import RequestMiddleware

logger.info("Starting TargetHub...")

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Embedded Lab Orchestration Platform",
)

app.add_middleware(RequestMiddleware)
app.add_exception_handler(
    TargetHubException,
    targethub_exception_handler,
)

app.include_router(api_router)


@app.on_event("startup")
async def startup():
    logger.info("Database initialized")
    logger.info("Application startup complete")


@app.on_event("shutdown")
async def shutdown():
    logger.info("Application shutdown complete")


@app.get("/")
async def root():
    return {
        "application": settings.app_name,
        "version": settings.app_version,
        "status": "running",
    }
