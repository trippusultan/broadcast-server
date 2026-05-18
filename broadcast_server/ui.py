"""Rich-powered terminal UI for the broadcast client.

Modes:
  classic  – original plain-text output (default)
  fancy    – full dashboard: header bar, message history panel,
             live stats sidebar, and a bordered input line

The parser understands a leading ``--ui MODE`` before the sub-command::

    broadcast-server --ui fancy connect -u alice
    broadcast-server --ui classic start --port 8765

If ``--ui`` is omitted the value of the ``BROADCAST_UI`` env-var is used
(``fancy`` / ``classic``).  Defaults to ``fancy`` when Rich is importable.
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

# ---------------------------------------------------------------------------
# Optional Rich import
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, TaskID, TextColumn
    from rich.table import Table
    from rich.text import Text
    from rich.theme import Theme

    HAS_RICH = True
except ImportError:  # pragma: no cover
    HAS_RICH = False

# ---------------------------------------------------------------------------
# Messages that never leave this module (no import cycles)
# ---------------------------------------------------------------------------

_STYLE = {
    "border": "cyan",
    "accent": "magenta",
    "ok": "green",
    "warn": "yellow",
    "err": "red bold",
    "system": "dim cyan",
    "history": "dim",
    "me": "bold cyan",
    "other": "white",
}

_MAX_HISTORY = 200
_REFRESH_SECS = 0.5


# ============================================================
# Helper – theme-aware console
# ============================================================
def _make_console(no_color: bool = False):
    if not HAS_RICH:
        return Console(no_color=True, force_terminal=True)  # type: ignore[return-value]
    theme = Theme(
        {
            "ok": _STYLE["ok"],
            "warn": _STYLE["warn"],
            "err": _STYLE["err"],
            "sys": _STYLE["system"],
            "me": _STYLE["me"],
            "other": _STYLE["other"],
            "border": _STYLE["border"],
            "accent": _STYLE["accent"],
        }
    )
    return Console(
        theme=theme,
        no_color=no_color,
        force_terminal=True,
        width=120,  # wide enough for 2-column layout
    )


# ============================================================
# Classic mode – plain text, one message per line
# ============================================================
class ClassicOutput:
    def __init__(self, console: Console):
        self._c = console

    def print(self, msg: dict):
        mtype = msg.get("type")
        if mtype == "system":
            self._c.print(f"[sys][system] {msg.get('message')}[/]")
        elif mtype == "history":
            ts = msg.get("timestamp", "")
            self._c.print(f"[dim][history]{ts}[/] [other]{msg.get('username', '')}[/]: {msg.get('message', '')}")
        else:
            self._c.print(f"[other]{msg.get('username', '')}[/]: [white]{msg.get('message', '')}[/]")


# ============================================================
# Fancy mode – split-panel live dashboard
# ============================================================
class FancyDashboard:
    """Manages a Rich ``Live`` display while the background tasks run."""

    def __init__(self, console: Console, username: str):
        self._c = console
        self._username = username
        self._messages: deque[dict] = deque(maxlen=_MAX_HISTORY)
        self._started = time.time()

        # Stats
        self._sent = 0
        self._received = 0
        self._peers: set[str] = set()

        # Layout
        self._layout = Layout()
        self._layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body", size=None),
        )
        self._layout["body"].split_row(
            Layout(name="chat", ratio=3),
            Layout(name="sidebar", ratio=1),
        )

        self._progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=None),
            expand=True,
        )
        self._progress_task: TaskID | None = None

        self._live = Live(
            self._layout,
            console=console,
            refresh_per_second=4,
            screen=False,
        )

    # ---- public ------------------------------------------------

    def start(self):
        self._live.start()

    def stop(self):
        self._live.stop()

    def add_message(self, msg: dict):
        self._messages.append(msg)
        if msg.get("type") == "message":
            self._received += 1

    def record_sent(self):
        self._sent += 1

    def set_peers(self, peers: set[str]):
        self._peers = peers

    # ---- internal -----------------------------------------------

    def _render_header(self) -> Panel:
        uptime = int(time.time() - self._started)
        mins, secs = divmod(uptime, 60)
        title = Text()
        title.append(" BROADCAST SERVER ", style="bold black on cyan")
        title.append("  ", style="")
        title.append(f"   Connected as ", style="white")
        title.append(self._username, style="bold cyan")
        title.append(f"   ◎ {mins:02d}:{secs:02d}", style="dim")
        return Panel(title, style="border", border_style="border")

    def _render_chat(self) -> Panel:
        lines: list[Text] = []
        for msg in self._messages:
            mtype = msg.get("type")
            if mtype == "system":
                t = Text()
                t.append(" ◈ ", style="sys")
                t.append(msg.get("message", ""), style="sys")
                lines.append(t)
            elif mtype == "history":
                t = Text()
                t.append(f"[{msg.get('timestamp', '')}] ", style="history")
                who = msg.get("username", "")
                if who == self._username:
                    t.append(f"{who}", style="me")
                else:
                    t.append(who, style="other")
                t.append(f": {msg.get('message', '')}", style="white")
                lines.append(t)
            elif mtype == "message":
                t = Text()
                who = msg.get("username", "")
                if who == self._username:
                    t.append(f"▸ {who}", style="me")
                else:
                    t.append(f"  {who}", style="other")
                t.append(f": {msg.get('message', '')}", style="white")
                lines.append(t)
        content = "\n".join(str(t) for t in lines) if lines else "[dim]No messages yet…[/]"
        return Panel(
            content,
            title="[accent]Live Feed",
            border_style="border",
            padding=(0, 1),
        )

    def _render_sidebar(self) -> Panel:
        # Peers table
        t = Table(show_header=True, header_style="bold cyan", box=None)
        t.add_column("Who", style="other", no_wrap=True)
        t.add_column("Status", style="ok")
        for peer in sorted(self._peers):
            flag = "● you" if peer == self._username else "● online"
            style = "me" if peer == self._username else "ok"
            t.add_row(Text(peer, style=style), Text(flag, style=style))
        if not self._peers:
            t.add_row("—", "[dim]waiting…[/]")

        # Stats
        stats_table = Table(show_header=False, box=None, padding=(0, 1))
        stats_table.add_row("Sent",   Text(str(self._sent),   style="me"))
        stats_table.add_row("Recv'd", Text(str(self._received), style="ok"))

        self._progress.update(self._progress_task, completed=self._received)
        prog_block = self._progress.get_renderable(self._progress_task)

        help_text = (
            "[bold]/me[/]  highlight yours\n"
            "[bold]/quit[/]  leave\n"
            "Just type and hit Enter"
        )

        from rich.column import Column  # inside to keep import happy
        sidebar_content = Column(t, stats_table, prog_block, Text(help_text, style="dim"), padding=(0, 1))
        return Panel(
            sidebar_content,
            title="[accent]Status",
            border_style="border",
            padding=(0, 1),
        )

    def update_progress(self, completed: int, total: int):
        if self._progress_task is None:
            self._progress_task = self._progress.add_task("msgs this session", total=total or None, completed=completed)
        else:
            self._progress.update(self._progress_task, completed=completed)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    def tick(self):
        self._layout["header"].update(self._render_header())
        self._layout["chat"].update(self._render_chat())
        self._layout["sidebar"].update(self._render_sidebar())


# ============================================================
# Fancy-mode main loop
# ============================================================
async def _fancy_chat(
    url: str,
    username: str,
    password: str,
    console: Console,
) -> None:
    import websockets

    try:
        ws = await websockets.connect(url)
    except Exception as exc:
        console.print(f"[err]Could not connect: {exc}[/]")
        sys.exit(1)

    dash = FancyDashboard(console, username)
    dash._progress_task = dash._progress.add_task("recv", total=None)
    active_peers = {username}

    with dash:
        # Send auth
        await ws.send(json.dumps({"username": username, "password": password}))

        async def receive():
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                dash.add_message(msg)
                if msg.get("type") == "message":
                    new_peer = msg.get("username")
                    if new_peer and new_peer not in active_peers:
                        active_peers.add(new_peer)
                    dash.set_peers(active_peers)
                dash.tick()

        async def send():
            loop = asyncio.get_running_loop()
            while True:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                text = line.rstrip("\n")
                if text.lower() in ("/quit", "/exit", "/q"):
                    break
                await ws.send(json.dumps({"message": text}))
                dash.record_sent()
                dash.tick()

        try:
            await asyncio.gather(receive(), send())
        except asyncio.CancelledError:
            pass
        finally:
            await ws.close()


# ============================================================
# Classic-mode main loop
# ============================================================
async def _classic_chat(
    url: str,
    username: str,
    password: str,
    console: Console,
) -> None:
    import websockets

    try:
        ws = await websockets.connect(url)
    except Exception as exc:
        console.print(f"[err]Could not connect: {exc}[/]")
        sys.exit(1)

    out = ClassicOutput(console)
    await ws.send(json.dumps({"username": username, "password": password}))

    async def receive():
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            out.print(msg)

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

    console.print(f"[ok]Connected as '{username}'[/].  Type /quit to leave.")
    try:
        await asyncio.gather(receive(), send())
    except asyncio.CancelledError:
        pass
    finally:
        await ws.close()


# ============================================================
# Public entry-points called from cli.py
# ============================================================
def chat(
    url: str,
    username: str,
    password: str = "",
    mode: str | None = None,
) -> None:
    """Main client entry point.

    Parameters
    ----------
    url, username, password:
        Forwarded to the server.
    mode:
        ``"classic"`` | ``"fancy"`` | ``None`` – ``None`` respects the
        ``BROADCAST_UI`` env-var, defaulting to ``fancy`` when Rich is
        available.
    """
    if mode is None:
        mode = os.environ.get("BROADCAST_UI", "fancy" if HAS_RICH else "classic")

    console = _make_console(no_color=(mode == "classic" and not HAS_RICH))

    if mode == "fancy" and HAS_RICH:
        asyncio.run(_fancy_chat(url, username, password, console))
    else:
        asyncio.run(_classic_chat(url, username, password, console))


def connect(*args, **kwargs):
    """Thin wrapper kept for backwards-compatibility."""
    chat(*args, **kwargs)
