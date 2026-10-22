from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import TargetHubException
from app.core.handlers import targethub_exception_handler
from app.core.logging import logger
from app.core.metrics import metrics
from app.core.middleware import RequestMiddleware
from app.db.session import SessionLocal

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
REACT_DIR = WEB_DIR / "react"
REACT_ASSETS_DIR = REACT_DIR / "assets"

if REACT_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=REACT_ASSETS_DIR), name="react-assets")


@app.on_event("startup")
async def startup():
    logger.info("Database initialized")
    logger.info("Application startup complete")


@app.on_event("shutdown")
async def shutdown():
    logger.info("Application shutdown complete")


@app.get("/")
async def root():
    return RedirectResponse(url="/app", status_code=307)


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
async def health_ready():
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return {"status": "ready", "database": "ok"}
    except Exception as exc:  # pragma: no cover - readiness failure path
        logger.warning(f"Readiness check failed: {exc}")
        return PlainTextResponse("not ready", status_code=503)


@app.get("/metrics", include_in_schema=False)
async def prometheus_metrics():
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    if (REACT_DIR / "index.html").exists():
        return FileResponse(REACT_DIR / "index.html")
    return FileResponse(WEB_DIR / "index.html")


@app.get("/app", include_in_schema=False)
@app.get("/app/{path:path}", include_in_schema=False)
async def react_app(path: str = ""):
    if (REACT_DIR / "index.html").exists():
        return FileResponse(REACT_DIR / "index.html")
    return FileResponse(WEB_DIR / "index.html")


@app.get("/legacy-dashboard", include_in_schema=False)
async def legacy_dashboard():
    return FileResponse(WEB_DIR / "index.html")
