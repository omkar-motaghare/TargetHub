import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

os.environ.setdefault("SECRET_KEY", "test-secret-key")

import pytest

from app.core.exceptions import ConflictResource, ResourceNotFound
from app.services.reservation_service import ReservationService


@dataclass
class FakeTarget:
    id: str
    enabled: bool = True
    status: str = "available"


@dataclass
class FakeReservation:
    id: str
    target_id: str
    user_id: str
    starts_at: datetime
    ends_at: datetime
    status: str = "active"
    released_at: datetime | None = None


class FakeReservationRepo:
    def __init__(self):
        self.items: list[FakeReservation] = []

    def expire_due(self, now):
        return 0

    def list(self, target_id=None, user_id=None):
        return self.items

    def get(self, reservation_id):
        return next((r for r in self.items if r.id == reservation_id), None)

    def find_overlapping_active(self, target_id, starts_at, ends_at):
        for r in self.items:
            if r.target_id == target_id and r.status == "active":
                if starts_at < r.ends_at and ends_at > r.starts_at:
                    return r
        return None

    def create(self, reservation):
        self.items.append(reservation)
        return reservation

    def update(self, reservation):
        return reservation


class FakeTargetRepo:
    def __init__(self, targets):
        self.targets = {t.id: t for t in targets}

    def get(self, target_id):
        return self.targets.get(target_id)

    def update(self, target):
        return target


class FakeSessionRepo:
    def __init__(self):
        self.closed: list[tuple[str, datetime]] = []

    def close_active_for_reservation(self, reservation_id: str, now: datetime) -> int:
        self.closed.append((reservation_id, now))
        return 1


def _service(targets):
    return ReservationService(FakeReservationRepo(), FakeTargetRepo(targets), FakeSessionRepo())


def _window(minutes_ahead_start=0, minutes_len=30):
    start = datetime.now(UTC) + timedelta(minutes=minutes_ahead_start)
    return start, start + timedelta(minutes=minutes_len)


def test_create_reservation_success():
    service = _service([FakeTarget("t1")])
    start, end = _window()
    reservation = service.create_reservation("t1", "user1", start, end)
    assert reservation.target_id == "t1"
    assert reservation.status == "active"


def test_create_reservation_missing_target():
    service = _service([])
    start, end = _window()
    with pytest.raises(ResourceNotFound):
        service.create_reservation("missing", "user1", start, end)


def test_create_reservation_conflict_is_rejected():
    service = _service([FakeTarget("t1")])
    start, end = _window()
    service.create_reservation("t1", "user1", start, end)
    with pytest.raises(ConflictResource):
        service.create_reservation("t1", "user2", start, end)


def test_release_requires_owner():
    service = _service([FakeTarget("t1")])
    start, end = _window()
    reservation = service.create_reservation("t1", "user1", start, end)
    with pytest.raises(ConflictResource, match="owner"):
        service.release_reservation(reservation.id, "user2")


def test_force_release_marks_released():
    service = _service([FakeTarget("t1")])
    start, end = _window()
    reservation = service.create_reservation("t1", "user1", start, end)
    released = service.force_release_reservation(reservation.id)
    assert released.status == "released"


def test_release_closes_active_sessions_for_reservation():
    service = _service([FakeTarget("t1")])
    start, end = _window()
    reservation = service.create_reservation("t1", "user1", start, end)

    released = service.release_reservation(reservation.id, "user1")

    assert released.status == "released"
    assert service.session_repository.closed
    closed_reservation_id, _closed_at = service.session_repository.closed[0]
    assert closed_reservation_id == reservation.id


def test_force_release_closes_active_sessions_for_reservation():
    service = _service([FakeTarget("t1")])
    start, end = _window()
    reservation = service.create_reservation("t1", "user1", start, end)

    released = service.force_release_reservation(reservation.id)

    assert released.status == "released"
    assert service.session_repository.closed
    closed_reservation_id, _closed_at = service.session_repository.closed[0]
    assert closed_reservation_id == reservation.id
