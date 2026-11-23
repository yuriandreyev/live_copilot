# Live AI Copilot

Local AI copilot for support conversations. The WP01 scaffold provides the API
liveness endpoint and local PostgreSQL and RabbitMQ infrastructure. WP03 adds database
migrations and session HTTP endpoints.

## Prerequisites

Python 3.12, uv, GNU Make, and a running Docker Engine with Docker Compose v2.

## Local startup

Run from the repository root. Place the [multilingual small model files](https://huggingface.co/Systran/faster-whisper-small/tree/536b066)
(`config.json`, `model.bin`, `tokenizer.json`, and `vocabulary.txt`) in
`models/faster-whisper-small/` before starting the API.

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

Open http://localhost:8000 in Chromium, select **Start capture**, and allow
microphone access. Speak briefly, then select **Stop** to flush and finalize
the capture. By default, the API loads the local model once at startup and
transcribes Russian on CPU in `int8` mode.
Run the audio conversion tests with `node --test tests/web/audio-worklet.test.cjs`.

The API loads settings from `.env` and gives process environment variables
precedence. The PostgreSQL database, username and password and the RabbitMQ
username and password are required. `LOG_LEVEL` defaults to `INFO`.
The example passwords are local development placeholders. PostgreSQL listens
on loopback port 5432, RabbitMQ on 5672, and RabbitMQ management on 15672.

Set `ASR_LANGUAGE=auto` for language detection. The model path, device, and
compute type are configurable via `ASR_MODEL_PATH`, `ASR_DEVICE`, and
`ASR_COMPUTE_TYPE`. Set `ASR_BACKEND=fake` for a deterministic demo
without model files. Missing or invalid local weights fail startup.

Run `make smoke WAV=path/to/speech.wav` with a mono 16 kHz PCM16 WAV
containing several seconds of continuous Russian speech. The smoke test
requires both an interim and a final result. It uses local weights and
accepts model and language overrides through `python -m transcription.smoke`.

For live recommendations, run llama.cpp locally with a loaded chat model.
The default endpoint is `LLM_ENDPOINT=http://127.0.0.1:8080/v1` and the
default model is `LLM_MODEL=Forge-1-E2B-Q4_K_M.gguf`. Check the served model
with `curl -f http://127.0.0.1:8080/v1/models`. Set `LLM_ENABLED=false` to
run transcript-only capture. If local inference fails, capture continues
and the recommendation panel shows a diagnostic fallback.

Run `UV_CACHE_DIR=.uv-cache uv run --locked --no-sync python -m bootstrap.llm_smoke`
to verify the duplicate-notification scenario against the running model.
Set `LLM_ENDPOINT` and `LLM_MODEL` in the command environment to override the
smoke test defaults. Live recommendations appear in the browser during
capture. Database persistence for them is scheduled for WP08.

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

The recognizer revises the current interim transcript and finalizes utterances
after a pause, the maximum utterance length, or a stop command. The database
currently records the session lifecycle. Transcript persistence arrives in WP08.
