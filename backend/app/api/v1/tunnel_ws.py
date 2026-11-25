"""Raw TCP tunnel to a board service (SSH, Telnet, GDB remote) over WebSocket.

The Agent next to the hardware opens the connection to a destination fixed in its own
configuration; the hub only relays bytes, so nothing here can pick a host or port::

    -> {"type": "auth", "token": "<access token>"}      (text frame, first)
    <- {"type": "ready", "session_id": "..."}             (text)
    -> <binary frame>                                     bytes for the board
    <- <binary frame>                                     bytes from the board
    <- {"type": "notice", "message": "..."}               (text, e.g. dropped bytes)
    <- {"type": "closed", "reason": "..."}                (text; socket then closes)

Like the serial console, every read and write goes through the session-gated operation
transport, so ownership, expiry and the capability binding are re-checked continuously.
The ``targethub tunnel`` CLI command turns this into a local TCP port for ssh, telnet or gdb.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import resolve_principal
from app.api.v1.serial_ws import (
    AUTH_TIMEOUT_SECONDS,
    READ_SIZE,
    READ_WAIT_MS,
    _db_session,
    _drain,
    _send,
)
from app.core.exceptions import ConflictResource, ResourceNotFound
from app.core.metrics import metrics

router = APIRouter(tags=["Sessions"])

MAX_FRAME_BYTES = 65536


@router.websocket("/sessions/{session_id}/tunnel/ws")
async def tunnel(websocket: WebSocket, session_id: str) -> None:
    from app.api.v1.sessions import build_gateway

    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
        token = json.loads(first).get("token") if first else None
    except (TimeoutError, json.JSONDecodeError, WebSocketDisconnect, KeyError, RuntimeError):
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=4401)
        return

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
        metrics.inc("targethub_tunnel_ws_connections_total")
        stop = asyncio.Event()
        db_calls: set[asyncio.Task] = set()

        async def guarded(coro):
            task = asyncio.create_task(coro)
            db_calls.add(task)
            task.add_done_callback(db_calls.discard)
            return await asyncio.shield(task)

        async def pump_output() -> None:
            try:
                await _pump_output()
            except (RuntimeError, WebSocketDisconnect):
                stop.set()

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
                    if "in time" in message:
                        await _send(websocket, {"type": "notice", "message": message})
                        await asyncio.sleep(1)
                        continue
                    await _send(websocket, {"type": "closed", "reason": message})
                    stop.set()
                    return
                data = result.get("data") or {}
                if data.get("dropped_bytes"):
                    await _send(
                        websocket,
                        {"type": "notice", "message": f"{data['dropped_bytes']} bytes were dropped (buffer full)"},
                    )
                payload = base64.b64decode(data.get("data_b64") or "")
                if payload:
                    await websocket.send_bytes(payload)
                if data.get("eof"):
                    await _send(websocket, {"type": "closed", "reason": "The board closed the connection"})
                    stop.set()
                    return

        async def pump_input() -> None:
            while not stop.is_set():
                try:
                    message = await websocket.receive()
                except (WebSocketDisconnect, RuntimeError):
                    stop.set()
                    return
                if message.get("type") == "websocket.disconnect":
                    stop.set()
                    return
                raw = message.get("bytes")
                if raw is None:
                    text = message.get("text")
                    if text:
                        with contextlib.suppress(json.JSONDecodeError):
                            if json.loads(text).get("type") == "ping":
                                await _send(websocket, {"type": "pong"})
                    continue
                for offset in range(0, len(raw), MAX_FRAME_BYTES):
                    chunk = raw[offset : offset + MAX_FRAME_BYTES]
                    encoded = base64.b64encode(chunk).decode("ascii")
                    try:
                        await guarded(writer.execute_async(session_id, username, "write", {"data_b64": encoded}))
                    except (ConflictResource, ResourceNotFound) as exc:
                        await _send(websocket, {"type": "notice", "message": f"write failed: {exc}"})
                        break

        output_task = asyncio.create_task(pump_output())
        input_task = asyncio.create_task(pump_input())
        try:
            await asyncio.wait({output_task, input_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            stop.set()
            await _drain((output_task, input_task), set(db_calls), session_id)
            with contextlib.suppress(BaseException):
                await websocket.close()
