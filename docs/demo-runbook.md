# Live AI Copilot demo runbook

## Fresh start

Complete the model and environment setup in the [README](../README.md). For
the English script below, start the API with `ASR_LANGUAGE=en`.

```sh
make infra-up
make migrate
ASR_LANGUAGE=en make run-api
```

Run `make run-worker` in a separate terminal. Check
`curl -fsS http://127.0.0.1:8000/readyz` before opening
`http://127.0.0.1:8000` in Chromium.

Select **Start capture**, grant microphone access, and read this synthetic
support dialogue at a steady pace.

> Our customers receive duplicate API notifications. The same event appears
> twice in the webhook history. Could you help me find the cause?

During capture the UI shows **Live** and incremental transcript text. Select
**Stop** and wait for the final transcript and recommendation. The expected
citation is `duplicate-notifications`. A relevant action compares event IDs
and checks whether the consumer processes the same event twice.

Copy the session ID from the WebSocket URL in the browser's Network panel,
set `COPILOT_SESSION_ID` to that UUID in your terminal, and query the stored
transcript and report.

```sh
curl -fsS "http://127.0.0.1:8000/api/sessions/$COPILOT_SESSION_ID/transcript"
curl -fsS "http://127.0.0.1:8000/api/sessions/$COPILOT_SESSION_ID/report"
curl -fsS http://127.0.0.1:8000/metrics
docker compose exec -T rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged
```

## Prerecorded input fallback

Generate the 16 kHz mono PCM WAV on macOS. The fixture is synthetic and contains
no customer recording. Label the input as prerecorded whenever demonstrating it.

```sh
bash demo/generate-fixture.sh
```

Open the local page in a separate Chromium tab. Paste the contents of
[`demo/prerecorded-input.js`](../demo/prerecorded-input.js) into that tab's
DevTools console and select the generated WAV in the file field. The helper
substitutes a local Web Audio stream for microphone input until you reload the
tab.

Click **Start capture**, wait for the fixture to play and stop the capture
after about 10 seconds. Check the same transcript, recommendation, and report
as in the spoken walkthrough. Reload the tab to return to physical microphone
input.

## Worker outage

1. Stop the worker with Ctrl-C in its terminal. Leave the API running.
2. Capture and complete another session. Check the transcript in the UI and
   through `GET /api/sessions/{id}/transcript`.
3. Run the queue command above. The default `live-copilot.v1` queue should have
   ready events and the new session report should still be empty.
4. Run `make run-worker` and repeat the queue and report checks. Ready and
   unacknowledged counts should fall to zero. The report should contain one
   summary. Run the replay check below to verify the duplicate-effect count.

```sh
UV_CACHE_DIR=.uv-cache uv run --locked --no-sync pytest \
  tests/integration/test_rabbitmq_delivery.py::test_confirmed_message_replays_after_publisher_exits_before_marking_database
```

The test checks one PostgreSQL processed marker and one summary after
two confirmed deliveries of the completion event.

## Broker outage

Stop only the broker and complete a session. The transcript endpoint remains
available and the API logs `outbox.pending` as the pending count changes.

```sh
docker compose stop rabbitmq
```

Start the broker again after completing the session.

```sh
docker compose up --wait rabbitmq
```

The publisher resumes delivery and the worker reconnects. Check that the report
appears and the queue drains.

## Automated failure injection

```sh
UV_CACHE_DIR=.uv-cache uv run --locked --no-sync pytest tests/integration/test_rabbitmq_delivery.py
```

The tests use temporary databases and isolated RabbitMQ queues. They stop and
restart the worker process, simulate a refused broker connection, and interrupt
the publisher after a real broker confirm but before the database mark. They
assert that replay creates one processed marker and one summary. They also check
that malformed messages and exhausted retries reach the dead-letter queue.
