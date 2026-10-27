"""Interactive serial console over WebSocket.

Browsers cannot set an Authorization header on a WebSocket, and tokens in
URLs leak into proxy logs, so the first client frame carries the token::

    -> {"type": "auth", "token": "<access token>"}
    <- {"type": "ready", "session_id": "...", "mode": "agent"}
    -> {"type": "input", "data": "ls\\r"}
    <- {"type": "output", "data": "..."}
    <- {"type": "notice", "message": "..."}         (e.g. dropped bytes)
    <- {"type": "closed", "reason": "..."}           (session ended; socket closes)

Output is pulled from the Agent with long reads (``wait_ms``) through the
same session-gated operation transport as the HTTP endpoints, so every read
re-checks session ownership, expiry and the capability binding, and it
works with any number of API workers.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Iterator

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_db, resolve_principal
from app.core.exceptions import ConflictResource, ResourceNotFound
from app.core.logging import logger
from app.core.metrics import metrics

router = APIRouter(tags=["Sessions"])

AUTH_TIMEOUT_SECONDS = 10
READ_WAIT_MS = 2000
READ_SIZE = 65536
MAX_INPUT_CHARS = 4096
IDLE_BACKOFF_SECONDS = 0.15
SHUTDOWN_GRACE_SECONDS = 20


@contextlib.contextmanager
def _db_session(websocket: WebSocket) -> Iterator[Session]:
    """Open a DB session honouring dependency overrides (used by tests)."""
    factory = websocket.app.dependency_overrides.get(get_db, get_db)
    generator = factory()
    db = next(generator)
    try:
        yield db
    finally:
        with contextlib.suppress(StopIteration):
            next(generator)


async def _drain(pumps, db_calls: set, session_id: str) -> None:
    """Stop the pumps and wait for in-flight DB work, even if being cancelled.

    Pumps only await the socket or shielded DB tasks, so cancelling them is
    safe; the DB tasks themselves must finish before their sessions close.
    """
    for task in pumps:
        task.cancel()
    pending = set(pumps) | {task for task in db_calls if not task.done()}
    # Shield: when the handler itself is being cancelled (server shutdown, test
    # client teardown) anyio re-delivers cancellation at every await.
    with anyio.CancelScope(shield=True):
        await asyncio.wait(pending, timeout=SHUTDOWN_GRACE_SECONDS)
    for task in set(pumps) | db_calls:
        if task.done() and not task.cancelled():
            exc = task.exception()
            if exc is not None and not isinstance(exc, (WebSocketDisconnect, RuntimeError, ConflictResource, ResourceNotFound)):
                logger.warning(f"serial console error for session {session_id}: {exc}")


async def _send(websocket: WebSocket, payload: dict) -> None:
    await websocket.send_text(json.dumps(payload))


@router.websocket("/sessions/{session_id}/serial/ws")
async def serial_console(websocket: WebSocket, session_id: str) -> None:
    from app.api.v1.sessions import build_gateway

    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
        token = json.loads(first).get("token") if first else None
    except (TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
        await websocket.close(code=4401)
        return

    # Separate DB sessions for the reader and writer: a SQLAlchemy Session must
    # not be used from two threads at once.
    with _db_session(websocket) as reader_db, _db_session(websocket) as writer_db:
        user = await run_in_threadpool(resolve_principal, reader_db, token or "")
        if user is None:
            await _send(websocket, {"type": "closed", "reason": "Authentication failed"})
            await websocket.close(code=4401)
            return
        username = user.username
        reader = build_gateway(reader_db)
        writer = build_gateway(writer_db)

        try:
            await reader.execute_async(session_id, username, "open")
        except (ConflictResource, ResourceNotFound) as exc:
            await _send(websocket, {"type": "closed", "reason": str(exc)})
            await websocket.close(code=4409)
            return

        await _send(websocket, {"type": "ready", "session_id": session_id})
        metrics.inc("targethub_serial_ws_connections_total")
        stop = asyncio.Event()
        db_calls: set[asyncio.Task] = set()

        async def guarded(coro):
            """Run DB-touching work in its own task so cancelling a pump cannot interrupt it."""
            task = asyncio.create_task(coro)
            db_calls.add(task)
            task.add_done_callback(db_calls.discard)
            return await asyncio.shield(task)

        async def pump_output() -> None:
            try:
                await _pump_output()
            except (RuntimeError, WebSocketDisconnect):
                stop.set()  # socket already closed

        async def _pump_output() -> None:
            while not stop.is_set():
                try:
                    result = await guarded(
                        reader.execute_async(
                            session_id, username, "read", {"size": READ_SIZE, "wait_ms": READ_WAIT_MS}
                        )
                    )
                except (ConflictResource, ResourceNotFound) as exc:
                    message = str(exc)
                    if "in time" in message:  # transient Agent hiccup: keep the console alive
                        await _send(websocket, {"type": "notice", "message": message})
                        await asyncio.sleep(1)
                        continue
                    await _send(websocket, {"type": "closed", "reason": message})
                    stop.set()
                    return
                data = result.get("data") or {}
                text = data.get("data_text") or ""
                if data.get("dropped_bytes"):
                    await _send(
                        websocket,
                        {"type": "notice", "message": f"{data['dropped_bytes']} bytes of output were dropped (buffer full)"},
                    )
                if text:
                    await _send(websocket, {"type": "output", "data": text})
                else:
                    # Hub-side providers return immediately; avoid a hot loop.
                    await asyncio.sleep(IDLE_BACKOFF_SECONDS)

        async def pump_input() -> None:
            while not stop.is_set():
                try:
                    raw = await websocket.receive_text()
                except (WebSocketDisconnect, RuntimeError):
                    stop.set()
                    return
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = message.get("type")
                if kind == "ping":
                    await _send(websocket, {"type": "pong"})
                    continue
                if kind != "input":
                    continue
                text = str(message.get("data", ""))[:MAX_INPUT_CHARS]
                if not text:
                    continue
                try:
                    await guarded(writer.execute_async(session_id, username, "write", {"text": text}))
                except (ConflictResource, ResourceNotFound) as exc:
                    await _send(websocket, {"type": "notice", "message": f"write failed: {exc}"})

        output_task = asyncio.create_task(pump_output())
        input_task = asyncio.create_task(pump_input())
        try:
            await asyncio.wait({output_task, input_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop.set()
            # In-flight reads/writes must finish before the DB sessions close below;
            # a snapshot of db_calls is taken because done-callbacks shrink the set.
            await _drain((output_task, input_task), set(db_calls), session_id)
            with contextlib.suppress(BaseException):
                await websocket.close()
