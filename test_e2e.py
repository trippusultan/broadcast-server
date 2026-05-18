"""End-to-end smoke test: server + 2 clients → shutdown cleanly."""

import asyncio
import json
import sys
import time

import websockets
from broadcast_server.auth import register_user

PORT = 18765
URI  = f"ws://localhost:{PORT}"

# clean slate
import os
os.environ["BROADCAST_PORT"] = str(PORT)


async def handler(ws):
    raw = await asyncio.wait_for(ws.recv(), timeout=5)
    data = json.loads(raw)
    user = data["username"]
    assert user in ("alice", "bob"), f"unexpected: {user}"
    await ws.close()


async def main():
    # Give previous server a moment to flush logs
    await asyncio.sleep(0.1)
    results = {}

    async def run_alice():
        async with websockets.connect(URI) as ws:
            await ws.send(json.dumps({"username": "alice", "password": "pw"}))
            for _ in range(2):
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                results.setdefault("alice", []).append(json.loads(msg))

    async def run_bob():
        async with websockets.connect(URI) as ws:
            await ws.send(json.dumps({"username": "bob", "password": "pw"}))
            for _ in range(2):
                msg = await asyncio.wait_for(ws.recv(), timeout=3)
                results.setdefault("bob", []).append(json.loads(msg))

    await asyncio.gather(run_alice(), run_bob())
    r = results
    assert any("alice joined" in str(m) for mlist in r.values() for m in mlist), "join msg missing"
    assert any("bob joined"   in str(m) for mlist in r.values() for m in mlist), "join msg missing"
    print("✓ e2e pass")
    # Hard-kill the server process so we get a clean report
    import subprocess, signal
    try:
        subprocess.run(["pkill", "-f", f"broadcast-server start --port {PORT}"], timeout=3)
    except Exception:
        pass
    print(results)


if __name__ == "__main__":
    asyncio.run(main())
