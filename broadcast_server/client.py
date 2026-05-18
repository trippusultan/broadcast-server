"""Broadcast Server — Rich terminal UI client."""

import asyncio
import json
import sys
from collections import defaultdict

import click
import websockets
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text


console = Console()
layout = Layout()

# ── shared state ──────────────────────────────────────────────────────────────
state = {
    "username": "",
    "messages": defaultdict(list),  # username → [str]
    "users": set(),
    "history": [],
    "connected": False,
    "input_buffer": "",
}

MAX_HISTORY = 60
MAX_USERS_TABLE_ROWS = 8


# ══════════════════════════════════════════════════════════════════════════════
# Rendering helpers
# ══════════════════════════════════════════════════════════════════════════════

def _header() -> Panel:
    title = Text(" BROADCAST SERVER ", style="bold on #1a1a2e")
    subtitle = Text("Real-time WebSocket Chat", style="dim #888888", justify="center")
    grid = Table.grid(padding=(0, 2))
    grid.add_row(title)
    grid.add_row(subtitle)
    return Panel(grid, style="on #0f0f1a", border_style="#4a5568", padding=(0, 1))


def _build_message_panel() -> Panel:
    body = Table.grid(padding=(0, 1))
    body.expand = True

    # ── broadcast history ────────────────────────────────────────────────
    for entry in state["history"][-MAX_HISTORY:]:
        mtype, *parts = entry
        body.add_row(_render_message(mtype, *parts))

    if not state["history"]:
        body.add_row(Text("  Waiting for messages…", style="dim #555555"))

    return Panel(
        body,
        title="[bold #60a5fa]Live Feed",
        border_style="#60a5fa",
        style="on #050510",
    )


def _render_message(mtype, *parts):
    if mtype == "join":
        user = parts[0] if parts else "?"
        return Text(f"  [bright_green]●[/] {user} joined", style="")
    if mtype == "leave":
        user = parts[0] if parts else "?"
        return Text(f"  [bright_red]●[/] {user} left", style="")
    if mtype == "msg":
        user = parts[0] if len(parts) > 0 else "?"
        text = parts[1] if len(parts) > 1 else ""
        author = Text(f"[{user}]", style="bold cyan") if user != state["username"] else Text(f"[{user}]", style="bold green")
        return Text.assemble("  ", author, " ", Text(text, style="#e2e8f0"))
    if mtype == "own":
        user = parts[0] if len(parts) > 0 else "?"
        text = parts[1] if len(parts) > 1 else ""
        return Text.assemble("  ", Text(f"[{user}]", style="bold #fbbf24"), " ", Text(text, style="#fef3c7"))
    if mtype == "sys":
        msg = parts[0] if parts else ""
        return Text(f"  [dim #6b7280]◈ {msg}[/]", style="dim")
    if mtype == "err":
        msg = parts[0] if parts else ""
        return Text(f"  [bright_red]⚠ {msg}[/]", style="")
    return Text(f"  {mtype}: {' '.join(p for p in parts if p)}", style="dim #555555")


def _build_users_panel() -> Panel:
    rows = []
    for user in sorted(state["users"]):
        style = "bold green" if user == state["username"] else "#60a5fa"
        rows.append(Text(f"  ● {user}", style=style))
    if not rows:
        rows = [Text("  no one here", style="dim #555555")]

    t = Table.grid(padding=(0, 0))
    for r in rows[:MAX_USERS_TABLE_ROWS]:
        t.add_row(r)

    return Panel(t, title="[bold #a78bfa]Users", border_style="#a78bfa", style="on #050510")


def _build_footer() -> Panel:
    prefix = Text(f" [{state['username']}] ", style="reverse bold #1a1a2e")
    bar = Text.assemble(prefix, " ", state["input_buffer"], style="#e2e8f0")
    return Panel(bar, style="on #0f0f1a", border_style="#4a5568")


def _build_layout() -> Layout:
    layout.split_column(
        Layout(_header(), size=3),
        Layout(name="body"),
        Layout(_build_footer(), size=3),
    )
    layout["body"].split_row(
        Layout(_build_message_panel(), name="msgs"),
        Layout(_build_users_panel(), name="users", size=22),
    )
    return layout


# ══════════════════════════════════════════════════════════════════════════════
# ws reader
# ══════════════════════════════════════════════════════════════════════════════

async def reader(ws):
    """Receive frames, append to state.history and update users list."""
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type", "")
            if mtype == "message":
                user = msg.get("username", "?")
                text = msg.get("message", "")
                key = "own" if user == state["username"] else "msg"
                state["history"].append((key, user, text))
                state["users"].add(user)
            elif mtype == "system":
                state["history"].append(("sys", msg.get("message", "")))
            elif mtype == "history":
                state["history"].append(("hist", msg.get("username","?"), msg.get("message","")))
            elif mtype == "join":
                user = msg.get("message", "").replace(" joined", "").strip()
                if user:
                    state["users"].add(user)
            elif mtype == "leave":
                user = msg.get("message", "").replace(" left", "").strip()
                if user and user in state["users"]:
                    state["users"].discard(user)
            else:
                state["history"].append(("err", str(msg)))
            # trim
            if len(state["history"]) > MAX_HISTORY * 2:
                state["history"] = state["history"][-MAX_HISTORY:]
    except Exception as e:
        state["history"].append(("err", str(e)))


# ══════════════════════════════════════════════════════════════════════════════
# stdin reader
# ══════════════════════════════════════════════════════════════════════════════

async def stdin_reader(send_q: asyncio.Queue):
    """Read lines from stdin and push to the send queue."""
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        text = line.rstrip("\n")
        if text.lower() in ("/quit", "/exit", "/q"):
            await send_q.put(None)
            break
        state["input_buffer"] = ""
        if text.strip():
            await send_q.put(text)


async def sender(ws, send_q: asyncio.Queue):
    """Consume the send queue and write to the websocket."""
    while True:
        text = await send_q.get()
        if text is None:
            await ws.close()
            return
        try:
            await ws.send(json.dumps({"message": text}))
        except Exception as e:
            state["history"].append(("err", f"send: {e}"))


# ══════════════════════════════════════════════════════════════════════════════
# Live rendering loop — polls frame into screen
# ══════════════════════════════════════════════════════════════════════════════

async def _tick(live):
    """Called every 50 ms — update the footer bar and refresh."""
    state["input_buffer"] = state["input_buffer"]  # no-op; future: live char echo
    live.update(_build_layout(), refresh=True)


async def _render_loop(live, send_q: asyncio.Queue):
    """Drive Live while stdin feeder + ws sender run in parallel."""
    ticker = asyncio.create_task(_async_poll(live, send_q))
    try:
        await send_q.get()   # sentinel → quit requested
    finally:
        ticker.cancel()
        try:
            await ticker
        except asyncio.CancelledError:
            pass


async def _async_poll(live, send_q):
    """Minimal busy-poll — Rich Live needs a coroutine, not a thread call."""
    while True:
        live.refresh()
        _update_footer_from_sendq(send_q)
        await asyncio.sleep(0.05)


def _update_footer_from_sendq(send_q: asyncio.Queue):
    """Non-blocking peek — reads current stdin into state.input_buffer."""
    # This runs inside the event loop; we can't block here.
    # Real-time keystroke display is handled by stdin_reader → send_q.
    # This is a pass-through; footer updates on Live.refresh().
    pass


# ══════════════════════════════════════════════════════════════════════════════
# Public entry point
# ══════════════════════════════════════════════════════════════════════════════

async def chat(url: str, username: str, password: str = ""):
    state["username"] = username
    try:
        ws = await websockets.connect(url)
    except Exception as e:
        console.print(f"[bright_red]✗[/] Could not connect: {e}")
        sys.exit(1)

    await ws.send(json.dumps({"username": username, "password": password}))

    send_q: asyncio.Queue = asyncio.Queue()
    tasks = [
        asyncio.create_task(reader(ws)),
        asyncio.create_task(stdin_reader(send_q)),
        asyncio.create_task(sender(ws, send_q)),
    ]

    with Live(
        _build_layout(),
        console=console,
        screen=True,
        refresh_per_second=20,
    ) as live:
        try:
            await _render_loop(live, send_q)
        except KeyboardInterrupt:
            pass
        finally:
            await send_q.put(None)
            for t in tasks:
                t.cancel()
            for t in tasks:
                try:
                    await t
                except asyncio.CancelledError:
                    pass


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

@click.command()
@click.argument("url", default="ws://localhost:8765")
@click.option("--username", "-u", prompt="Username")
@click.option("--password", "-p", default="", hide_input=True)
def connect(url, username, password):
    """Connect to a broadcast server — Rich terminal UI."""
    try:
        asyncio.run(chat(url, username, password))
    except KeyboardInterrupt:
        console.print("\n[dim]Disconnected.[/]")


if __name__ == "__main__":
    connect()
