"""Simple authentication for broadcast server clients."""

import json
import os
import hashlib
import secrets

AUTH_FILE = os.path.expanduser("~/.broadcast-server-users.json")


def _load_users():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE) as f:
            return json.load(f)
    return {}


def _save_users(users):
    os.makedirs(os.path.dirname(AUTH_FILE), exist_ok=True)
    with open(AUTH_FILE, "w") as f:
        json.dump(users, f, indent=2)


def register_user(username, password):
    """Register a new user. Returns True if created, False if already exists."""
    users = _load_users()
    if username in users:
        return False
    salt = secrets.token_hex(16)
    pwhash = hashlib.sha256((salt + password).encode()).hexdigest()
    users[username] = {"salt": salt, "hash": pwhash}
    _save_users(users)
    return True


def authenticate(username, password):
    """Verify credentials. Returns True if valid."""
    users = _load_users()
    if username not in users:
        return False
    record = users[username]
    pwhash = hashlib.sha256((record["salt"] + password).encode()).hexdigest()
    return pwhash == record["hash"]