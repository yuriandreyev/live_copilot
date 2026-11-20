# Live AI Copilot

Local AI copilot for support conversations. The WP01 scaffold provides the API
liveness endpoint and local PostgreSQL and RabbitMQ infrastructure. WP03 adds database
migrations and session HTTP endpoints.

## Prerequisites

Python 3.12, uv, GNU Make, and a running Docker Engine with Docker Compose v2.

## Local startup

Run from the repository root.

```sh
cp .env.example .env
make sync
make infra-up
docker compose ps
make migrate
make run-api
```

In a second terminal, run `curl -f http://localhost:8000/healthz`.
Expect HTTP 200 and `{"status":"ok"}`. The probe checks API liveness and
does not connect to PostgreSQL or RabbitMQ.

The API loads settings from `.env` and gives process environment variables
precedence. The PostgreSQL database, username and password and the RabbitMQ
username and password are required. `LOG_LEVEL` defaults to `INFO`.
The example passwords are local development placeholders. PostgreSQL listens
on loopback port 5432, RabbitMQ on 5672, and RabbitMQ management on 15672.

## Developer commands

| Command | Purpose |
| --- | --- |
| `make sync` | Install the project and development tools from `uv.lock` |
| `make lint` | Check lint and formatting with Ruff and types with mypy |
| `make format` | Format Python files |
| `make test` | Run the unit and integration tests |
| `make verify` | Run lint, formatting, type checks, and the full test suite |
| `make run-api` | Start the API at http://localhost:8000 |
| `make run-worker` | Run the worker scaffold, which reports its status and exits. Event consumption arrives in WP09. |
| `make infra-up` | Start PostgreSQL and RabbitMQ and wait for both to become healthy |
| `make infra-down` | Stop and remove the infrastructure containers while retaining their data volumes |
| `make db-up` / `make db-down` | Start or stop PostgreSQL alone |
| `make migrate` | Apply pending PostgreSQL schema migrations |

Before running `make test` or `make verify`, start PostgreSQL with
`make db-up`. The configured development role needs permission to create
the temporary integration test database.

## Session API

| Request | Result |
| --- | --- |
| `POST /api/sessions` | HTTP 201 with a new UUID and `created` status |
| `GET /api/sessions/{id}` | State, timestamps, and summary availability |
| `GET /api/sessions/{id}/transcript` | Utterances ordered by sequence, with their recommendations ordered by context version |
| `GET /api/sessions/{id}/report` | Stored summary and summary timestamp, both null until a summary exists |

The read endpoints return HTTP 404 for unknown session IDs. PostgreSQL
defaults to `127.0.0.1:5432`. To connect the API or Alembic elsewhere, set
`POSTGRES_HOST` and `POSTGRES_PORT`.

## WebSocket capture scaffold

Connect to `/ws/sessions/{id}` using the UUID returned by `POST /api/sessions`.
Send a JSON command with `schema_version: 1`, `session_id`, and
`event_type: "capture.start"`. Wait for `session.status` with
`payload.status: "live"` before sending binary frames. Each frame contains
mono, 16 kHz, signed little-endian PCM16, with 2 to 3,200 bytes and a whole
number of samples. Send `capture.stop` with the same envelope to finish.

One capture can run at a time. If the 30-frame audio queue fills, the server
sends `session.overloaded` and terminates capture. A normal stop has up to
five seconds to drain through the recognizer. Disconnecting before completion
marks the session interrupted.

WP04 uses a fake recognizer. Its interim and final messages contain simulated
text, and the database records the session lifecycle. Transcript persistence
arrives in WP08.
