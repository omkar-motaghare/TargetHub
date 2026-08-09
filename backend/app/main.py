from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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

WEB_DIR = Path(__file__).parent / "web"
app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


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


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return FileResponse(WEB_DIR / "index.html")
