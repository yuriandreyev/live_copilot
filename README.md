# Live AI Copilot

Local AI copilot for support conversations. The WP01 scaffold provides the API
liveness endpoint and local PostgreSQL and RabbitMQ infrastructure.

## Prerequisites

Python 3.12, uv, GNU Make, and a running Docker Engine with Docker Compose v2.

## Local startup

Run from the repository root.

```sh
cp .env.example .env
make sync
make infra-up
docker compose ps
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
| `make lint` | Check lint and formatting |
| `make format` | Format Python files |
| `make test` | Run pytest |
| `make run-api` | Start the API at http://localhost:8000 |
| `make run-worker` | Run the worker scaffold, which reports its status and exits. Event consumption arrives in WP09. |
| `make infra-up` | Start PostgreSQL and RabbitMQ and wait for both to become healthy |
| `make infra-down` | Stop and remove the infrastructure containers while retaining their data volumes |
| `make db-up` / `make db-down` | Start or stop PostgreSQL alone |
| `make migrate` | Reports that migrations are unavailable until WP03 and exits with an error |
