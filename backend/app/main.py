from fastapi import FastAPI

from app.core.config import settings
from app.core.logging import logger

logger.info("Starting TargetHub...")

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Embedded Lab Orchestration Platform",
)


@app.on_event("startup")
async def startup():
    logger.info("Application startup complete")


@app.on_event("shutdown")
async def shutdown():
    logger.info("Application shutdown complete")


@app.get("/")
async def root():
    logger.info("Root endpoint accessed")

    return {
        "application": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "status": "running",
    }


@app.get("/health")
async def health():
    logger.info("Health endpoint accessed")

    return {
        "status": "healthy",
        "environment": settings.environment,
    }
