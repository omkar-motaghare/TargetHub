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
