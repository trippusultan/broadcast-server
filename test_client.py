"""Quick client test — connect to running server and verify broadcast."""

import asyncio
import json
import sys
import websockets

PORT = 18765
URI  = f"ws://localhost:{PORT}"

async def test():
    import broadcast_server.auth
    broadcast_server.auth.register_user("alice", "pw")
    broadcast_server.auth.register_user("bob",   "pw")

    async def run(name, password):
        async with websockets.connect(URI) as ws:
            await ws.send(json.dumps({"username": name, "password": password}))
            msgs = []
            # grab 3 msgs: <peer joined> + <peer joined> + own name echoed? depends
            while len(msgs) < 3:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
                print(f"[{name}] {json.loads(raw)}")
                msgs.append(json.loads(raw))

    await asyncio.gather(run("alice", "pw"), run("bob", "pw"))
    print("✓ test complete")

    import subprocess, signal
    try:
        subprocess.run(["pkill", "-f", f"broadcast-server start --port {PORT}"], timeout=3)
    except Exception:
        pass

asyncio.run(test())
