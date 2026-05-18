"""Thin re-export shim — client.connect now delegates to ui.chat."""

from broadcast_server.ui import chat, connect  # noqa
__all__ = ["chat", "connect"]
