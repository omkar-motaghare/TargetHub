import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import logger
from app.core.metrics import metrics

QUIET_PATHS = {"/health", "/health/live", "/health/ready"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}
SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def resolve_request_id(incoming: str | None) -> str:
    if incoming and SAFE_REQUEST_ID.match(incoming):
        return incoming
    return str(uuid.uuid4())


class RequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = resolve_request_id(request.headers.get("x-request-id"))

        start = time.perf_counter()
        quiet = request.url.path in QUIET_PATHS

        with logger.contextualize(request_id=request_id):
            if not quiet:
                logger.info(f"--> {request.method} {request.url.path}")

            response = await call_next(request)

            elapsed = (time.perf_counter() - start) * 1000

            response.headers["X-Request-ID"] = request_id
            for name, value in SECURITY_HEADERS.items():
                response.headers.setdefault(name, value)

            metrics.inc(
                "targethub_http_requests_total",
                labels={"method": request.method, "status": str(response.status_code)},
            )

            if not quiet:
                logger.info(f"<-- {response.status_code} ({elapsed:.2f} ms)")

        return response
