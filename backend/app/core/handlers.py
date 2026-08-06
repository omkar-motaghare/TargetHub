from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    DuplicateResource,
    ResourceNotFound,
    TargetHubException,
)


async def targethub_exception_handler(
    request: Request,
    exc: TargetHubException,
):
    if isinstance(exc, ResourceNotFound):
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    if isinstance(exc, DuplicateResource):
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc)},
        )

    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )
