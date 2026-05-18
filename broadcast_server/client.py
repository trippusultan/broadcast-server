"""Interactive CLI client for the broadcast server."""

import asyncio
import json
import sys

import click
import websockets


async def chat(url: str, username: str, password: str = ""):
    try:
        ws = await websockets.connect(url)
    except Exception as e:
        click.echo(f"Could not connect: {e}", err=True)
        sys.exit(1)

    # Send auth (empty password = no-auth mode)
    await ws.send(json.dumps({"username": username, "password": password}))

    async def receive():
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "system":
                click.echo(f"[system] {msg.get('message')}")
            elif mtype == "history":
                click.echo(f"[{msg.get('timestamp', '')}] {msg.get('username', '')}: {msg.get('message', '')}")
            else:
                click.echo(f"{msg.get('username', '')}: {msg.get('message', '')}")

    async def send():
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            text = line.rstrip("\n")
            if text.lower() in ("/quit", "/exit"):
                break
            await ws.send(json.dumps({"message": text}))

    click.echo(f"Connected as '{username}'.  Type /quit to leave.")
    await asyncio.gather(receive(), send())
    await ws.close()


@click.command()
@click.argument("url", default="ws://localhost:8765")
@click.option("--username", "-u", prompt="Username", help="Your display name")
@click.option("--password", "-p", default="", help="Password (omit for no-auth mode)", hide_input=True)
def connect(url, username, password):
    """Connect to a broadcast server."""
    try:
        asyncio.run(chat(url, username, password))
    except KeyboardInterrupt:
        click.echo("\nDisconnected.")


if __name__ == "__main__":
    connect()
