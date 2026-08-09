from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ProviderOperationResult:
    """Normalized result returned by a TargetHub provider operation."""

    success: bool
    message: str = ""
    data: dict[str, Any] | None = None


class TargetProvider(ABC):
    """Base contract for hardware/network providers.

    Providers translate TargetHub's capability-level operations into
    hardware- or protocol-specific actions. Authorization belongs to the
    control/session layer; providers should execute only authorized work.
    """

    provider_key: str

    @abstractmethod
    def health_check(self) -> ProviderOperationResult:
        """Return provider availability/health."""
        raise NotImplementedError
