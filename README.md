**[Project URL](https://roadmap.sh/projects/broadcast-server)**

# Broadcast Server

A WebSocket-based broadcast server with a CLI for real-time messaging.

## Usage

```bash
# Install
pip install -e .

# Start the server
broadcast-server start --port 8765

# In another terminal — register a user (optional)
broadcast-server register -u alice -p secret

# Connect as a client
broadcast-server connect ws://localhost:8765 -u alice -p secret

# Or no-auth mode (empty password)
broadcast-server connect ws://localhost:8765 -u guest
```

## Features

- **Broadcast** — every message from any client is relayed to all others in real-time
- **Auth** — optional SHA-256 password hashing stored in `~/.broadcast-server-users.json`
- **History** — last 100 messages persisted to `~/.broadcast-server-history.json`; new clients receive the last 20 on connect
- **Graceful handling** — dead sockets pruned, clean disconnect announcements
- **CLI** — `start`, `connect`, `register`, `status` subcommands

## Protocol

Clients send JSON:

```json
{ "type": "auth", "username": "alice", "password": "secret" }
{ "type": "message", "message": "Hello everyone!" }
```

Server sends JSON as one of:

| type | payload |
|---|---|
| `history` | `username`, `message`, `timestamp` — replay on connect |
| `message` | `username`, `message` — regular broadcast |
| `system` | `message` — join/leave notifications |
