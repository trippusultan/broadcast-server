"""CLI entry point:  broadcast-server start|connect|register."""

import json
import os

import click

from broadcast_server.auth import register_user
from broadcast_server.ui import chat as ui_chat


@click.group()
@click.version_option()
@click.option("--ui", "ui_mode", default=None,
              type=click.Choice(["classic", "fancy", "auto"], case_sensitive=False),
              help="Terminal UI mode (classic / fancy / auto). 'auto' uses fancy when Rich is available.")
def cli(ui_mode):
    """Broadcast Server — WebSocket real-time messaging."""
    if ui_mode == "auto":
        os.environ["BROADCAST_UI"] = "fancy"
    elif ui_mode:
        os.environ["BROADCAST_UI"] = ui_mode


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
    ui = os.environ.get("BROADCAST_UI", "fancy")
    ui_chat(url, username, password, mode=None)


@cli.command()
@click.option("--username", "-u", prompt="Username", required=True)
@click.option("--password", "-p", prompt="Password", hide_input=True, required=True)
def register(username, password):
    """Register a new user (saved locally for server auth)."""
    from broadcast_server.auth import register_user as _reg
    if _reg(username, password):
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
