class TargetHubException(Exception):
    """Base application exception."""


class ResourceNotFound(TargetHubException):
    def __init__(self, resource: str, identifier: str):
        self.resource = resource
        self.identifier = identifier
        super().__init__(f"{resource} '{identifier}' not found")


class DuplicateResource(TargetHubException):
    def __init__(self, resource: str, identifier: str):
        self.resource = resource
        self.identifier = identifier
        super().__init__(f"{resource} '{identifier}' already exists")


class ConflictResource(TargetHubException):
    """Raised when a requested operation conflicts with current state."""

    def __init__(self, message: str):
        super().__init__(message)


class AuthenticationError(TargetHubException):
    """Raised when an Agent credential cannot authenticate a request."""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(message)
