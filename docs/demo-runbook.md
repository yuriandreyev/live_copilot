# WP09 delivery and recovery runbook

Start PostgreSQL and RabbitMQ, apply the existing schema, and launch the API.

```sh
make infra-up
make migrate
make run-api
```

Run `make run-worker` in a separate terminal. Open the browser UI at
`http://127.0.0.1:8000`, start a capture, and describe duplicate API
notifications. Stop capture and keep the session ID from the browser's network
panel. The report endpoint eventually contains the worker's utterance and
recommendation counts.

```sh
curl -f "http://127.0.0.1:8000/api/sessions/$COPILOT_SESSION_ID/report"
docker compose exec -T rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged
```

## Worker outage

1. Stop the worker with Ctrl-C in its terminal. Leave the API running.
2. Capture and complete another session. Check the transcript in the UI and
   through `GET /api/sessions/{id}/transcript`.
3. Run the queue command above. The default `live-copilot.v1` queue should have
   ready events and the new session report should still be empty.
4. Run `make run-worker` and repeat the queue and report checks. Ready and
   unacknowledged counts should fall to zero. The report should contain one
   summary.

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
