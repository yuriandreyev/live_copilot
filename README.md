# Live AI Copilot

Live AI Copilot listens to a support conversation, updates the transcript as
you speak, and suggests a next step from a small FAQ. It runs ASR and language
inference on the local machine. PostgreSQL stores the final transcript and
recommendations. An independent RabbitMQ worker produces the session report.

See the [interview demo runbook](docs/demo-runbook.md) and the
[release handoff](docs/release-acceptance.md).

## Prerequisites

Python 3.12, uv, GNU Make, Docker Engine with Docker Compose v2, desktop
Chromium or Chrome, and a local llama.cpp server. The prerecorded fallback
generator uses macOS `say` and `afconvert`. Node.js runs the browser audio tests.

## Local startup

Run from the repository root. Place the [Systran multilingual small model files](https://huggingface.co/Systran/faster-whisper-small/tree/main)
(`config.json`, `model.bin`, `tokenizer.json`, and `vocabulary.txt`) in
`models/faster-whisper-small/` before starting the API. The reference
configuration uses Systran revision `536b066`. For recommendations, download
the Q4_K_M GGUF from the [Forge model card](https://huggingface.co/YoSaNoo/Forge-1-E2B)
and put it under `models/`. Start the [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)
in its own terminal.

```sh
llama-server --host 127.0.0.1 --port 8080 -m models/Forge-1-E2B-Q4_K_M.gguf
curl -fsS http://127.0.0.1:8080/v1/models
```

Set `LLM_MODEL` to the ID returned by the server if it differs from the default.
The model weights must be provisioned once. Runtime inference stays local.

```sh
cp .env.example .env
make sync
make infra-up
docker compose ps
make migrate
make run-api
```

In another terminal, start `make run-worker`. Check the API with
`curl -fsS http://127.0.0.1:8000/healthz` and
`curl -fsS http://127.0.0.1:8000/readyz`. The first checks liveness, and
the second shows whether PostgreSQL, RabbitMQ, and both model paths are ready.

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
without model files. Missing or invalid local weights leave the API running
with ASR unavailable in readiness and an `asr_unavailable` error on capture.

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
capture and are available afterward from the session transcript endpoint.

## Developer commands

| Command | Purpose |
| --- | --- |
| `make sync` | Install the project and development tools from `uv.lock` |
| `make lint` | Check lint and formatting with Ruff and types with mypy |
| `make format` | Format Python files |
| `make test` | Run the unit and integration tests |
| `make verify` | Run lint, formatting, type checks, and the full test suite |
| `make run-api` | Start the API at http://localhost:8000 |
| `make run-worker` | Consume RabbitMQ events and write session summaries |
| `make infra-up` | Start PostgreSQL and RabbitMQ and wait for both to become healthy |
| `make infra-down` | Stop and remove the infrastructure containers while retaining their data volumes |
| `make db-up` / `make db-down` | Start or stop PostgreSQL alone |
| `make migrate` | Apply pending PostgreSQL schema migrations |

Before running `make test` or `make verify`, start PostgreSQL and RabbitMQ
with `make infra-up`. The development credentials must allow creation of
temporary integration test databases and RabbitMQ queues.

## Background delivery

The API runs the outbox publisher in the background. Run `make run-worker`
in a separate terminal to process its messages and populate session reports.
Both processes use `RABBITMQ_HOST`, `RABBITMQ_PORT`, and `RABBITMQ_QUEUE`.
Setting `OUTBOX_ENABLED=false` pauses publishing while the API continues
recording events in PostgreSQL.

The publisher under `src/outbox` and consumer under `src/worker` each own
their application use cases, ports, and infrastructure adapters.
`src/bootstrap` wires both components, and `src/storage` holds their shared
PostgreSQL mappings. See the [recovery runbook](docs/demo-runbook.md) for
worker restart, broker outage, and replay checks.

## Readiness and metrics

`GET /healthz` checks liveness. `GET /readyz` checks PostgreSQL, RabbitMQ,
ASR, and the configured llama.cpp model separately and returns HTTP 503 if
a dependency is unavailable. When `LLM_ENABLED=false`, llama.cpp is reported
as disabled.

`GET /metrics` exposes Prometheus text metrics for capture activity, queue
depth, finalization and recommendation latency, inference failures, the
outbox backlog, and worker outcomes. Run the API and worker from the same
repository directory, or set `WORKER_METRICS_PATH` to the same local path
for both processes. Its default is `.cache/worker-metrics.json`.

Capture logs include event and correlation IDs with server-side timings.
The ASR timing estimates audio end from received samples. Recommendation
timing runs from transcript commit through recommendation commit.

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
after a pause, the maximum utterance length, or a stop command. The API saves
each finalized utterance or recommendation together with its outbox event
before sending the WebSocket update. The transcript endpoint returns
committed updates in order. If a write fails, the socket reports
`session.error` with code `persistence_failed`.

## Troubleshooting and limits

- For microphone permission errors, grant access to the local origin in
  Chromium and start a new capture. The runbook includes a synthetic fallback.
- For HTTP 503 from readiness, check the unavailable dependency in the JSON
  response. Check the ASR model path and query `/v1/models` on llama.cpp.
- If transcripts are saved while reports are empty, check the worker and
  RabbitMQ. Start the worker with `make run-worker` and check the report again.
- The demo supports one active capture. The reference run timings in the
  handoff describe individual observations. WP11 latency percentiles remain open.
