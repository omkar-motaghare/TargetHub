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
