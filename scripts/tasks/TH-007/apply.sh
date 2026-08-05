#!/usr/bin/env bash
set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT/backend"

echo "======================================="
echo " TargetHub - TH-007"
echo " Middleware & Exception Framework"
echo "======================================="

mkdir -p app/core

cat > app/core/exceptions.py <<'PY'
from fastapi import status


class TargetHubException(Exception):
    """Base exception for TargetHub."""

    def __init__(
        self,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ):
        self.message = message
        self.status_code = status_code
        super().__init__(message)
PY

cat > app/core/handlers.py <<'PY'
from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.exceptions import TargetHubException


async def targethub_exception_handler(
    request: Request,
    exc: TargetHubException,
):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.message,
            "path": request.url.path,
        },
    )
PY

cat > app/core/middleware.py <<'PY'
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import logger


class RequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = str(uuid.uuid4())

        start = time.perf_counter()

        logger.info(
            f"[{request_id}] --> {request.method} {request.url.path}"
        )

        response = await call_next(request)

        elapsed = (time.perf_counter() - start) * 1000

        response.headers["X-Request-ID"] = request_id

        logger.info(
            f"[{request_id}] <-- {response.status_code} ({elapsed:.2f} ms)"
        )

        return response
PY

python3 <<'PY'
from pathlib import Path

path = Path("app/main.py")
text = path.read_text()

if "RequestMiddleware" not in text:
    text = text.replace(
        "from app.core.logging import logger",
        """from app.core.logging import logger
from app.core.exceptions import TargetHubException
from app.core.handlers import targethub_exception_handler
from app.core.middleware import RequestMiddleware""",
    )

if "app.add_middleware(RequestMiddleware)" not in text:
    text = text.replace(
        ")",
        """)
app.add_middleware(RequestMiddleware)
app.add_exception_handler(
    TargetHubException,
    targethub_exception_handler,
)""",
        1,
    )

path.write_text(text)

print("✔ Updated app/main.py")
PY

echo
echo "TH-007 Applied Successfully"
