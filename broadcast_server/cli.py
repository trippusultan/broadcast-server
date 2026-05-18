"""CLI entry point:  broadcast-server start|connect|register."""

import json
import os

import click

from broadcast_server.auth import register_user


@click.group()
@click.version_option()
def cli():
    """Broadcast Server — WebSocket real-time messaging."""
    pass


@cli.command()
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8765, type=int)
def start(host, port):
    """Start the broadcast server."""
    from broadcast_server.server import main
    import asyncio
    asyncio.run(main(host, port))


@cli.command()
@click.argument("url", default="ws://localhost:8765")
@click.option("--username", "-u", prompt="Username")
@click.option("--password", "-p", default="", hide_input=True)
def connect(url, username, password):
    """Connect to a broadcast server as a client."""
    from broadcast_server.client import connect as _connect
    # Re-use client logic via import trick
    import asyncio
    from broadcast_server.client import chat
    try:
        asyncio.run(chat(url, username, password))
    except KeyboardInterrupt:
        click.echo("\nDisconnected.")


@cli.command()
@click.option("--username", "-u", prompt="Username", required=True)
@click.option("--password", "-p", prompt="Password", hide_input=True, required=True)
def register(username, password):
    """Register a new user (saved locally for server auth)."""
    from broadcast_server.auth import register_user
    if register_user(username, password):
        click.echo(f"User '{username}' registered successfully.")
    else:
        click.echo(f"User '{username}' already exists.", err=True)


@cli.command()
@click.option("--port", default=8765, type=int)
def status(port):
    """Check if server is running on localhost:PORT."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        result = s.connect_ex(("127.0.0.1", port))
        if result == 0:
            click.echo(f"Server is running on port {port}")
        else:
            click.echo(f"No server listening on port {port}")


if __name__ == "__main__":
    cli()
