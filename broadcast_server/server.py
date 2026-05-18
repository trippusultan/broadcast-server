"""WebSocket broadcast server with client management."""

import asyncio
import json
import logging
import signal
import sys
import time
from collections import defaultdict

import websockets

from broadcast_server.history import MessageHistory

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

connected_clients: dict = {}
history = MessageHistory()


async def broadcast(message: dict, exclude: str | None = None):
    """Send a JSON message to all connected clients except `exclude`."""
    if not connected_clients:
        return
    data = json.dumps(message)
    # fan-out concurrently, drop dead sockets
    tasks = []
    for ws, info in list(connected_clients.items()):
        if info["username"] == exclude:
            continue
        tasks.append(_safe_send(ws, data))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _safe_send(ws, data: str):
    try:
        await ws.send(data)
    except Exception:
        pass  # will be cleaned up on next loop


async def handle_client(websocket):
    """Handle a single client connection."""
    # First message must be auth: {"username": str, "password": str}
    try:
        raw = await asyncio.wait_for(websocket.recv(), timeout=10)
    except asyncio.TimeoutError:
        await websocket.close(code=1008, reason="auth timeout")
        return

    try:
        auth_msg = json.loads(raw)
    except json.JSONDecodeError:
        await websocket.close(code=1008, reason="invalid auth format")
        return

    username = auth_msg.get("username", "").strip()
    if not username:
        await websocket.close(code=1008, reason="username required")
        return

    # Password check — empty string means no-auth mode
    from broadcast_server.auth import authenticate
    password = auth_msg.get("password", "")
    if password != "" and not authenticate(username, password):
        await websocket.close(code=1008, reason="authentication failed")
        return

    connected_clients[websocket] = {"username": username}
    logger.info("Client connected: %s (total: %d)", username, len(connected_clients))

    # Send recent history
    for entry in history.get_recent(20):
        await _safe_send(websocket, json.dumps({"type": "history", **entry}))

    # Announce join
    await broadcast(
        {"type": "system", "message": f"{username} joined"},
        exclude=username,
    )

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            text = msg.get("message", "").strip()
            if not text:
                continue
            history.add(username, text)
            await broadcast(
                {"type": "message", "username": username, "message": text}
            )
    finally:
        del connected_clients[websocket]
        logger.info("Client disconnected: %s (total: %d)", username, len(connected_clients))
        await broadcast(
            {"type": "system", "message": f"{username} left"},
        )


async def heartbeat(stop_event: asyncio.Event):
    """Periodically prune dead sockets."""
    while not stop_event.is_set():
        dead = []
        for ws in list(connected_clients):
            try:
                await ws.ping()
            except Exception:
                dead.append(ws)
        for ws in dead:
            del connected_clients[ws]
        await asyncio.wait_for(stop_event.wait(), timeout=30)


async def main(host="0.0.0.0", port=8765):
    stop_event = asyncio.Event()

    def shutdown():
        logger.info("Shutting down…")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown)
        except NotImplementedError:
            pass  # Windows

    async with websockets.serve(handle_client, host, port, ping_interval=20, ping_timeout=10):
        logger.info("Broadcast server started on %s:%d", host, port)
        await heartbeat(stop_event)


if __name__ == "__main__":
    import click

    @click.command()
    @click.option("--host", default="0.0.0.0", help="Bind address")
    @click.option("--port", default=8765, type=int, help="Bind port")
    def start(host, port):
        """Start the broadcast server."""
        asyncio.run(main(host, port))

    start()
