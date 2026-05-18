"""Message history storage for broadcast server."""

import json
import os
import time
from collections import deque

HISTORY_FILE = os.path.expanduser("~/.broadcast-server-history.json")
MAX_HISTORY = 100


class MessageHistory:
    def __init__(self):
        self._messages = deque(maxlen=MAX_HISTORY)
        self._load()

    def _load(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE) as f:
                    data = json.load(f)
                    self._messages.extend(data[-MAX_HISTORY:])
            except (json.JSONDecodeError, TypeError):
                self._messages.clear()

    def _save(self):
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "w") as f:
            json.dump(list(self._messages), f, indent=2)

    def add(self, username, message):
        entry = {
            "username": username,
            "message": message,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._messages.append(entry)
        self._save()

    def get_recent(self, count=20):
        return list(self._messages)[-count:]