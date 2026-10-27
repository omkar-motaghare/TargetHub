import asyncio
import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.dependencies import bearer, get_auth_service, is_admin_user
from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import TargetHubException
from app.core.handlers import targethub_exception_handler
from app.core.logging import logger
from app.core.metrics import metrics
from app.core.middleware import RequestMiddleware
from app.db.session import SessionLocal
from app.services.auth_service import AuthService
from app.services.scheduler import scheduler_loop


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info(f"Starting {settings.app_name} {settings.app_version} ({settings.environment})")
    stop = asyncio.Event()
    task = asyncio.create_task(scheduler_loop(_app, stop)) if settings.scheduler_enabled else None
    yield
    stop.set()
    if task is not None:
        await task
    logger.info("Application shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Embedded Lab Orchestration Platform",
    lifespan=lifespan,
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


@app.get("/")
async def root():
    return RedirectResponse(url="/app", status_code=307)


@app.get("/health", include_in_schema=False)
@app.get("/health/live", include_in_schema=False)
async def health_live():
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
def health_ready():
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


def require_metrics_access(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    auth: AuthService = Depends(get_auth_service),
) -> None:
    """Allow the METRICS_TOKEN bearer or an admin JWT; everything else is 401."""
    unauthorized = HTTPException(
        status_code=401,
        detail="Metrics require a bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not credentials or credentials.scheme.lower() != "bearer":
        raise unauthorized
    expected = settings.metrics_token
    if expected and hmac.compare_digest(credentials.credentials, expected):
        return
    try:
        user = auth.user_for_bearer(credentials.credentials)
    except Exception:
        raise unauthorized from None
    if not is_admin_user(user):
        raise unauthorized


@app.get("/metrics", include_in_schema=False, dependencies=[Depends(require_metrics_access)])
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
