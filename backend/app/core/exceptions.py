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
