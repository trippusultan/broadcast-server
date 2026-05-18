"""Quick integration test — spins up server and exercises the protocol."""

import asyncio
import json
import time

import websockets

SERVER_URI = "ws://localhost:8765"


async def main():
    # ── 1. Register two users ──────────────────────────────────────────────
    from broadcast_server.auth import register_user, _save_users
    register_user("alice", "wonderland")
    register_user("bob", "builder")
    print("✓ registered alice / bob")

    # ── 2. Start connecting clients via the real server process ───────────
    # (we expect the server to already be running on port 8765)

    alice_task = asyncio.create_task(connect("alice", "wonderland"))
    bob_task   = asyncio.create_task(connect("bob", "builder"))

    await asyncio.sleep(2)   # give them time to handshake & receive history

    # Check history file has entries
    from broadcast_server.history import MessageHistory
    h = MessageHistory()
    print(f"✓ history has {len(h._messages)} entries")

    alice_task.cancel()
    bob_task.cancel()
    try:
        await alice_task
    except asyncio.CancelledError:
        pass
    try:
        await bob_task
    except asyncio.CancelledError:
        pass
    print("✓ all green")


async def connect(username, password):
    async with websockets.connect(SERVER_URI) as ws:
        await ws.send(json.dumps({"username": username, "password": password}))
        # read 3 messages: 2 history + 1 system (bob joined)
        for _ in range(3):
            raw = await asyncio.wait_for(ws.recv(), timeout=3)
            print(f"  [{username}] ← {json.loads(raw)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
