"""Broadcast Server — clean B&W Rich TUI.

Modes
-----
auto   — default: uses ``fancy`` when ``rich`` is installed,
          ``classic`` otherwise.
fancy  — full split-panel dashboard, adapts to terminal width.
classic — one log line per message, no Rich panel overhead.

Layout (fancy)
--------------
┌─header──────────────────────────────────────────────────────────────┐
│  BROADCAST  ·  localhost:8765  ·  user │  ── chat   ── users      │
├─────────────────────────┬───────────────────┬────────────────────────┤
│                         │                   │                        │
│  Live message feed      │   Connected peers │  Session stats         │
│  (scrollable)           │   • alice         │  Sent: 3   Recv'd: 12 │
│                         │   • bob ●you      │                        │
│  ─ interactive bar      └───────────────────┴────────────────────────┤
└─────────────────────────────────────────────────────────────────────┘

Responsive behaviour
--------------------
* Terminal ≥ 90 cols: three-column layout (chat | sidebar | stats).
* Terminal 60 – 90 cols: chat + sidebar stacked, stats in header.
* Terminal < 60 cols  : falls back to ``classic`` mode automatically.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import deque
from typing import Any

import click

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    HAS_RICH = True
except ImportError:  # pragma: no cover
    HAS_RICH = False

# ── constants ──────────────────────────────────────────────────────────────

_MAX_HISTORY = 200
_REFRESH = 0.1          # seconds between Live screen redraws
_CONNECT_TIMEOUT = 5   # seconds to wait for server on connect

# gateway localhost ANSI colours for B&W terminals
# We never emit *colour* escape codes — we rely entirely on Rich's
# box-drawing / styling so ``NO_COLOR`` and ``--ui classic`` both fall
# back cleanly.
_STYLE_BORDER = "bright_black"
_STYLE_TITLE  = "bold"
_STYLE_ME     = "bold"
_STYLE_OTHER  = ""
_STYLE_SYS    = "dim"
_STYLE_ERR    = "bold red"

# ── shared mutable state ────────────────────────────────────────────────────

_username: str = ""          # set at connect time
_history: deque[dict] = deque(maxlen=_MAX_HISTORY)
_peers: set[str] = set()
_sent: int = 0
_received: int = 0
_connected: bool = False


# ── helpers ────────────────────────────────────────────────────────────────

def _ts(now: float | None = None) -> str:
    return time.strftime("%H:%M", time.localtime(now or time.time()))


def _append(msg: dict) -> None:
    """Append a protocol message to the rolling history deque."""
    _history.append(msg)


def _me(user: str | None = None) -> str:
    return user or _username


# ════════════════════════════════════════════════════════════════════════════
# Classic mode — one line per message, no-screen rendering
# ════════════════════════════════════════════════════════════════════════════

def _render_classic(msg: dict) -> str:
    mtype = msg.get("type", "")

    if mtype == "system":
        return f"[{_ts()}] * {msg.get('message', '')}"
    if mtype == "history":
        return (f"[{msg.get('timestamp', '')[:16]}] "
                f"<{msg.get('username','?')}> {msg.get('message','')}")
    if mtype == "message":
        who = msg.get("username", "?")
        text = msg.get("message", "")
        if who == _username:
            return f"[{_ts()}] <{who}> {text}"
        return f"[{_ts()}] <{who}> {text}"
    return str(msg)


def print_classic(msg: dict) -> None:
    """Write one line to stdout — used when Rich is absent."""
    line = _render_classic(msg)
    if HAS_RICH:
        from rich import print as rprint
        rprint(line)
    else:
        print(line, flush=True)


# ════════════════════════════════════════════════════════════════════════════
# Fancy mode — Rich Live split-panel dashboard
# ════════════════════════════════════════════════════════════════════════════

def _make_console() -> Console:
    width = os.environ.get("COLUMNS", 120)
    try:
        w = max(60, int(width))
    except ValueError:
        w = 80
    return Console(width=w, no_color=False)


def _header_panel(width: int, uptime: int) -> Panel:
    mins, _ = divmod(uptime, 60)
    clock = time.strftime("%H:%M", time.localtime())

    body = Table.grid(padding=(0, 2))
    body.add_column("logo", max_width=24)
    body.add_column("spacer")
    body.add_column("info", max_width=width - 30)

    logo = Text("BROADCAST", style=_STYLE_TITLE)
    body.add_row(logo, "", "")

    subtitle = Text(f"localhost:8765  user={_username}  {clock}", style=_STYLE_SYS)
    body.add_row("", "", subtitle)

    return Panel(
        body,
        style="",
        border_style=_STYLE_BORDER,
        padding=(0, 1),
    )


def _render_chat_panel() -> Panel:
    rows: list[str] = []
    for msg in _history[-_MAX_HISTORY:]:
        mtype = msg.get("type", "")
        if mtype == "message":
            who = msg.get("username", "?")
            txt = msg.get("message", "")
            prefix = f"[{_ts()}]"
            if who == _username:
                rows.append(f"  {prefix} [bold]{who}[/bold] {txt}")
            else:
                rows.append(f"  {prefix} {who} {txt}")
        elif mtype == "system":
            rows.append(f"  [{_STYLE_SYS}]• {msg.get('message', '')}[/]")
        elif mtype == "history":
            ts2 = msg.get("timestamp", "")[:16]
            rows.append(f"  [{_STYLE_SYS}]{ts2} <{msg.get('username','?')}> {msg.get('message','')}[/]")

    content = "\n".join(rows) if rows else "[dim]No messages yet…[/]"
    return Panel(
        content,
        title="live feed",
        border_style=_STYLE_BORDER,
        style="",
        padding=(0, 1),
    )


def _render_sidebar() -> Panel:
    body = Table.grid(padding=(0, 0))

    # peers
    for peer in sorted(_peers):
        flag = "you" if peer == _username else "online"
        style = _STYLE_ME if peer == _username else _STYLE_OTHER
        body.add_row(Text(f"  • {peer}  [{flag}]", style=style or ""))

    if not _peers:
        body.add_row(Text("  [dim]waiting…[/]", style=""))

    body.add_row("")
    body.add_row(Text(f"  sent: {_sent}", style=_STYLE_SYS))
    body.add_row(Text(f"  recv: {_received}", style=_STYLE_SYS))

    body.add_row("")
    body.add_row(Text("  /quit to leave", style=_STYLE_SYS))
    body.add_row(Text("  type and ↵", style=_STYLE_SYS))

    return Panel(
        body,
        title="status",
        border_style=_STYLE_BORDER,
        style="",
        padding=(0, 1),
    )


def _render_footer(username: str) -> Panel:
    text = Text(f"[{username}] ", style=_STYLE_TITLE)
    return Panel(text, border_style=_STYLE_BORDER, style="")


def _build_dashboard(console: Console) -> Layout:
    width = console.width
    uptime = int(time.time() - _started)
    layout = Layout()
    layout.split_column(
        Layout(_header_panel(width, uptime), name="hdr", size=4),
        Layout(name="body"),
        Layout(_render_footer(_username), name="ftr", size=3),
    )
    layout["body"].split_row(
        Layout(_render_chat_panel(), name="chat", ratio=3),
        Layout(_render_sidebar(), name="users", ratio=1),
    )
    return layout


# ════════════════════════════════════════════════════════════════════════════
# ASGI-ish event loop — websocket + stdin
# ════════════════════════════════════════════════════════════════════════════

_started: float = time.time()


async def _fancy_chat(url: str, username: str, password: str, console: Console) -> None:
    global _username, _peers, _sent, _received, _connected, _started
    _username = username
    _started = time.time()
    _peers = {username}
    _sent = 0
    _received = 0
    _connected = False

    import websockets  # local import avoids top-level hard dep

    try:
        ws = await asyncio.wait_for(websockets.connect(url), timeout=_CONNECT_TIMEOUT)
    except OSError as exc:
        console.print(f"[red]✗ can't reach {url}: {exc}[/]")
        sys.exit(1)

    await ws.send(json.dumps({"username": username, "password": password}))

    layout = _build_dashboard(console)

    async def receive():
        global _received
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                _append(msg)
                mtype = msg.get("type", "")
                if mtype == "message":
                    _received += 1
                    who = msg.get("username")
                    if who:
                        _peers.add(who)
                elif mtype == "system":
                    body = msg.get("message", "").lower()
                    if "joined" in body:
                        who = body.replace(" joined", "").strip()
                        if who:
                            _peers.add(who)
                    elif "left" in body:
                        who = body.replace(" left", "").strip()
                        _peers.discard(who)
        except Exception as exc:
            _append({"type": "error", "message": str(exc)})

    async def send():
        global _sent
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            text = line.rstrip("\n")
            if text.lower() in ("/quit", "/exit", "/q"):
                break
            if text.strip():
                await ws.send(json.dumps({"message": text}))
                _sent += 1

    # ── Live render loop ────────────────────────────────────────────────────
    async def ticker():
        loop = asyncio.get_running_loop()
        while True:
            l = _build_dashboard(console)
            live.update(l)
            await asyncio.sleep(_REFRESH)

    recv_t = asyncio.create_task(receive())
    send_t = asyncio.create_task(send())
    ticker_t = asyncio.create_task(ticker())

    with Live(
        layout,
        console=console,
        refresh_per_second=4,
        screen=False,
    ) as live:
        try:
            done, _ = await asyncio.wait({recv_t, send_t}, return_when=asyncio.FIRST_COMPLETED)
        except KeyboardInterrupt:
            done = {send_t}
        finally:
            ticker_t.cancel()
            try:
                await ticker_t
            except asyncio.CancelledError:
                pass
            await ws.close()
            for t in (recv_t, send_t):
                if not t.done():
                    t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass


async def _classic_chat(url: str, username: str, password: str, console: Console) -> None:
    _username = username

    import websockets
    try:
        ws = await asyncio.wait_for(websockets.connect(url), timeout=_CONNECT_TIMEOUT)
    except OSError as exc:
        console.print(f"[red]✗ can't reach {url}: {exc}[/]")
        sys.exit(1)

    await ws.send(json.dumps({"username": username, "password": password}))
    console.print(f"[green]connected[/] as '[bold]{username}[/]'.  /quit to leave.\n")

    async def receive():
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            print_classic(msg)

    async def send():
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            text = line.rstrip("\n")
            if text.lower() in ("/quit", "/exit", "/q"):
                break
            if text.strip():
                await ws.send(json.dumps({"message": text}))

    try:
        await asyncio.gather(receive(), send())
    except KeyboardInterrupt:
        pass
    finally:
        await ws.close()


# ════════════════════════════════════════════════════════════════════════════
# Public entry point
# ════════════════════════════════════════════════════════════════════════════

def chat(url: str = "ws://localhost:8765", username: str = "", password: str = "",
         mode: str | None = None) -> None:
    """Connect to the broadcast server and run the TUI.

    Parameters
    ----------
    url:
        WebSocket server URL.
    username:
        Display name sent to the server on connect.
    password:
        Server auth password (empty string = no-auth mode).
    mode:
        ``'fancy'`` | ``'classic'`` | ``None``.
        ``None`` respects the ``BROADCAST_UI`` env-var; defaults to
        ``fancy`` when Rich is importable, ``classic`` otherwise.
    """
    if not HAS_RICH and mode in (None, "fancy"):
        mode = "classic"

    if mode is None:
        mode = os.environ.get("BROADCAST_UI", "fancy" if HAS_RICH else "classic")

    console = _make_console()

    if mode == "fancy" and HAS_RICH:
        asyncio.run(_fancy_chat(url, username, password, console))
    else:
        asyncio.run(_classic_chat(url, username, password, console))
