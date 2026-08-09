from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.providers.base import ProviderOperationResult, TargetProvider


@dataclass(slots=True)
class SerialProviderConfig:
    """Configuration for one serial provider instance."""

    provider_key: str
    port: str
    baudrate: int = 115200
    timeout: float = 0.2


class SerialProvider(TargetProvider):
    """First concrete TargetHub provider for serial-console capabilities.

    pyserial is imported lazily so TargetHub can still start when a deployment
    has no serial hardware attached. The provider owns only serial I/O; session
    authorization is performed by the session/control layer before an
    operation is dispatched here.
    """

    def __init__(self, config: SerialProviderConfig) -> None:
        self.config = config
        self.provider_key = config.provider_key
        self._serial: Any | None = None

    def health_check(self) -> ProviderOperationResult:
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError:
            return ProviderOperationResult(False, "pyserial is not installed")

        try:
            port = serial.Serial(
                self.config.port,
                baudrate=self.config.baudrate,
                timeout=self.config.timeout,
            )
            port.close()
            return ProviderOperationResult(
                True,
                "Serial port is available",
                {
                    "provider_key": self.provider_key,
                    "port": self.config.port,
                    "baudrate": self.config.baudrate,
                },
            )
        except (OSError, serial.SerialException) as exc:
            return ProviderOperationResult(
                False,
                f"Serial port is unavailable: {exc}",
                {
                    "provider_key": self.provider_key,
                    "port": self.config.port,
                },
            )

    def open(self) -> ProviderOperationResult:
        if self._serial is not None and self._serial.is_open:
            return ProviderOperationResult(True, "Serial connection already open")

        try:
            import serial  # type: ignore[import-not-found]

            self._serial = serial.Serial(
                self.config.port,
                baudrate=self.config.baudrate,
                timeout=self.config.timeout,
            )
            return ProviderOperationResult(True, "Serial connection opened")
        except (OSError, serial.SerialException) as exc:
            self._serial = None
            return ProviderOperationResult(False, f"Failed to open serial connection: {exc}")

    def close(self) -> ProviderOperationResult:
        if self._serial is None:
            return ProviderOperationResult(True, "Serial connection already closed")

        try:
            self._serial.close()
            return ProviderOperationResult(True, "Serial connection closed")
        finally:
            self._serial = None

    def write(self, data: bytes) -> ProviderOperationResult:
        if self._serial is None or not self._serial.is_open:
            return ProviderOperationResult(False, "Serial connection is not open")

        try:
            written = self._serial.write(data)
            return ProviderOperationResult(True, "Serial data written", {"bytes_written": written})
        except OSError as exc:
            return ProviderOperationResult(False, f"Failed to write serial data: {exc}")

    def read(self, size: int = 4096) -> ProviderOperationResult:
        if self._serial is None or not self._serial.is_open:
            return ProviderOperationResult(False, "Serial connection is not open")

        try:
            data = self._serial.read(size)
            return ProviderOperationResult(
                True,
                "Serial data read",
                {"data": data, "bytes_read": len(data)},
            )
        except OSError as exc:
            return ProviderOperationResult(False, f"Failed to read serial data: {exc}")
