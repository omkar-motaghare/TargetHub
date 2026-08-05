import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import logger


class RequestMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = str(uuid.uuid4())

        start = time.perf_counter()

        logger.info(f"[{request_id}] --> {request.method} {request.url.path}")

        response = await call_next(request)

        elapsed = (time.perf_counter() - start) * 1000

        response.headers["X-Request-ID"] = request_id

        logger.info(f"[{request_id}] <-- {response.status_code} ({elapsed:.2f} ms)")

        return response
