import os
import re

from fastapi import APIRouter, HTTPException

from app.providers.serial import SerialProvider, SerialProviderConfig

router = APIRouter(prefix="/providers", tags=["Providers"])


def _env_prefix(provider_key: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", provider_key).strip("_").upper()
    return f"TARGETHUB_{normalized}"


@router.get("/serial/{provider_key}/health")
def serial_health(provider_key: str):
    prefix = _env_prefix(provider_key)
    port = os.getenv(f"{prefix}_PORT")
    if not port:
        raise HTTPException(
            status_code=503,
            detail=f"Serial provider '{provider_key}' is not configured",
        )

    try:
        baudrate = int(os.getenv(f"{prefix}_BAUDRATE", "115200"))
        timeout = float(os.getenv(f"{prefix}_TIMEOUT", "0.2"))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Invalid serial provider configuration") from exc

    provider = SerialProvider(
        SerialProviderConfig(
            provider_key=provider_key,
            port=port,
            baudrate=baudrate,
            timeout=timeout,
        )
    )
    result = provider.health_check()
    if not result.success:
        raise HTTPException(status_code=503, detail=result.message)
    return result.data
