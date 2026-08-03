from fastapi import FastAPI

from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Embedded Lab Orchestration Platform",
)


@app.get("/")
async def root():
    return {
        "application": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "status": "running",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "environment": settings.environment,
    }
