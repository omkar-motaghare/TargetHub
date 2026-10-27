import uuid
from datetime import UTC, datetime

from app.core.exceptions import ConflictResource, ResourceNotFound
from app.models.session import TargetSession
from app.repositories.reservation_repository import ReservationRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.target_repository import TargetRepository
from app.services.capability_binding import validate_capability_runtime_binding


def _as_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime.

    SQLite commonly returns DATETIME values without timezone information even
    when the application supplied timezone-aware values. Treat naive values as
    UTC so reservation/session comparisons remain safe and deterministic.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SessionService:
    """Authorizes target access by binding a session to an active reservation."""

    def __init__(
        self,
        repository: SessionRepository,
        reservation_repository: ReservationRepository,
        target_repository: TargetRepository,
    ):
        self.repository = repository
        self.reservation_repository = reservation_repository
        self.target_repository = target_repository

    def list_sessions(self, user_id: str | None = None, target_id: str | None = None):
        self.repository.expire_due(datetime.now(UTC))
        return self.repository.list(user_id=user_id, target_id=target_id)

    def get_session(self, session_id: str):
        self.repository.expire_due(datetime.now(UTC))
        session = self.repository.get(session_id)
        if session is None:
            raise ResourceNotFound("Session", session_id)
        return session

    @staticmethod
    def _resolve_capability(target, capability_type: str, capability_id: str | None):
        if capability_id:
            capability = next(
                (item for item in target.capabilities if item.id == capability_id),
                None,
            )
            if capability is None:
                raise ConflictResource("Selected capability does not belong to the target")
            if capability.capability_type != capability_type:
                raise ConflictResource("Selected capability does not match capability_type")
            if not capability.enabled:
                raise ConflictResource("Selected capability is disabled")
            return capability

        matches = [
            item
            for item in target.capabilities
            if item.capability_type == capability_type and item.enabled
        ]
        if not matches:
            raise ConflictResource(
                f"Target does not have an enabled '{capability_type}' capability"
            )
        if len(matches) > 1:
            raise ConflictResource(
                f"Target has multiple enabled '{capability_type}' capabilities; specify capability_id"
            )
        return matches[0]

    def create_session(
        self,
        reservation_id: str,
        user_id: str,
        capability_type: str,
        capability_id: str | None = None,
    ):
        now = datetime.now(UTC)
        self.reservation_repository.expire_due(now)
        reservation = self.reservation_repository.get(reservation_id)
        if reservation is None:
            raise ResourceNotFound("Reservation", reservation_id)
        if reservation.user_id != user_id:
            raise ConflictResource("Only the reservation owner can open a session")

        reservation_starts_at = _as_utc(reservation.starts_at)
        reservation_ends_at = _as_utc(reservation.ends_at)
        if reservation.status != "active" or reservation_ends_at <= now:
            raise ConflictResource("Reservation is not active")
        if reservation_starts_at > now:
            raise ConflictResource("Reservation has not started yet")

        target = self.target_repository.get(reservation.target_id)
        if target is None:
            raise ResourceNotFound("Target", reservation.target_id)
        if not target.enabled:
            raise ConflictResource("Target is disabled")

        capability = self._resolve_capability(target, capability_type, capability_id)
        validate_capability_runtime_binding(capability, now=now)

        session = TargetSession(
            id=str(uuid.uuid4()),
            reservation_id=reservation.id,
            target_id=target.id,
            user_id=user_id,
            capability_type=capability.capability_type,
            provider_key=capability.provider_key,
            capability_id=capability.id,
            agent_id=capability.agent_id,
            resource_id=capability.resource_id,
            status="active",
            expires_at=reservation_ends_at,
        )
        return self.repository.create(session)

    def close_session(self, session_id: str, user_id: str):
        session = self.get_session(session_id)
        if session.user_id != user_id:
            raise ConflictResource("Only the session owner can close it")
        if session.status != "active":
            raise ConflictResource(f"Session '{session_id}' is already {session.status}")

        return self.repository.close(session, datetime.now(UTC))
