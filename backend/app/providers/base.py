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
    control/session layer; providers execute only work the gateway has
    already authorized for an active, owned session.
    """

    #: Capability type this provider serves (e.g. "serial", "power").
    capability_type: str = ""
    provider_key: str

    @abstractmethod
    def health_check(self) -> ProviderOperationResult:
        """Return provider availability/health."""
        raise NotImplementedError

    def operations(self) -> list[str]:
        """Return the operations this provider supports for the UI/gateway."""
        return ["health"]

    def execute(
        self, operation: str, params: dict[str, Any] | None = None
    ) -> ProviderOperationResult:
        """Dispatch a named operation. Base handles the shared 'health' op."""
        if operation == "health":
            return self.health_check()
        return ProviderOperationResult(False, f"Unsupported operation '{operation}'")
