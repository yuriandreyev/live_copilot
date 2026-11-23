# Live AI Copilot Implementation Plan

**Version:** 1.0\
**Status:** Ready for implementation\
**Audience:** Autonomous coding agent and technical reviewer\
**Target effort:** 5–7 focused evenings\
**Source of truth:** [Product Requirements](Live_AI_Copilot_PRD.md) and [System Architecture](ARCHITECTURE.md)

## 1. Mission and Guardrails

Implement a **single-user, local-only Live AI Copilot** that receives microphone audio over a FastAPI WebSocket, produces interim and final transcripts using local speech recognition, and displays AI recommendations grounded in a small FAQ. Persist finalized data in PostgreSQL. Deliver domain events to RabbitMQ reliably and demonstrate worker recovery without duplicated effects. Package the result as a reproducible repository and a 3–4 minute screencast.

This is a focused engineering demo, **not a production contact-center platform**. The audio hot path must not depend on RabbitMQ. No paid AI API or remote inference service is required.

### Instructions to the implementation agent

1. Read `Live_AI_Copilot_PRD.md` and `ARCHITECTURE.md` before modifying code. The implementation plan is the work order; the other two documents define behavior and rationale. If they conflict, stop and document the conflict instead of silently changing requirements.
2. Inspect the repository before creating files. Preserve unrelated files and user changes. Do not overwrite existing source or configuration without examining it.
3. Work through the numbered work packages in dependency order. Mark a package complete only when **every P0 acceptance checkbox passes** and verification output has been recorded.
4. Build a runnable vertical slice early. Prefer small modules with typed contracts, dependency injection, and replaceable ASR/LLM adapters. Avoid speculative abstractions and new services.
5. Keep the application offline-capable after models are provisioned. Do not introduce cloud APIs, account signup, telemetry exports, or secrets in the repository.
6. Use fake ASR/LLM adapters in automated tests. Real-model smoke tests are separate and explicitly labeled; a mocked demo must never be presented as a real inference result.
7. At the end of each work package, run applicable tests and record: files changed, commands run, outcomes, and remaining risks. Prefer one coherent commit per package when working in a Git repository.
8. If hardware limitations block a real-time target, measure and report the limitation, reduce model size or frequency, and preserve the backend architecture. Do not invent benchmark results.

### Priority labels

- **P0 — Required for the engineering demo:** must pass before release.
- **P1 — Valuable polish:** implement if the P0 path is stable and time remains.
- **P2 — Explicitly deferred:** not authorized by this plan.

P2 includes Kubernetes, Consul, Vault, authentication, multi-user scaling, diarization, telephony, vector search, advanced RAG, cloud deployment, and automatic reconnection of an active audio session.

## 2. Technical Baseline and Open Decisions

| Area | Initial implementation choice | Decision rule |
| --- | --- | --- |
| Language | Python 3.12, with versions locked in the project | Adjust only for documented host/runtime incompatibility |
| API | FastAPI, Pydantic, asyncio, WebSockets | One API process |
| Persistence | PostgreSQL, SQLAlchemy Async, `asyncpg`, Alembic | One `AsyncSession` per task/request; no concurrent session sharing |
| Messaging | RabbitMQ and an async Python AMQP client | Persistent events, publisher confirms, manual consumer acknowledgements |
| Local ASR | `faster-whisper`, configurable CPU `int8` baseline | Benchmark actual CPU/GPU before selecting a larger model |
| Local LLM | llama.cpp with one small model shared by two agent roles | Select model only after a timed local test |
| UI | Plain HTML, CSS, JavaScript, `AudioWorklet` | Chromium desktop is the initial manual test target |
| Deployment | Docker Compose for PostgreSQL and RabbitMQ; API, worker, and inference on host | Do not make GPU container compatibility a launch blocker |
| Tests | `pytest`, FastAPI test client, real PostgreSQL/RabbitMQ for integration tests | No model downloads or paid calls during normal CI tests |
| Quality | `ruff`, type checks where practical, formatter, structured logs | Pin versions; document supported commands |

Before committing to a model, record the development machine's **OS, CPU, GPU, RAM/VRAM, primary speech language, and selected model names**. These are currently unknown and must remain configurable. A script can start with CPU `int8` but must not assume that any particular latency target is already achievable.

## 3. Delivery Order

| Work package | Scope | Priority | Estimate | Depends on |
| --- | --- | --- | --- | --- |
| WP 00 | Hardware and inference feasibility spike | P0 | 1–2 h | None |
| WP 01 | Repository, tooling, infrastructure | P0 | 1–2 h | None |
| WP 02 | Domain contracts and session state machine | P0 | 1–2 h | WP 01 |
| WP 03 | PostgreSQL schema, repository layer, HTTP API | P0 | 2–3 h | WP 02 |
| WP 04 | WebSocket protocol and session orchestration | P0 | 2–3 h | WP 02, WP 03 |
| WP 05 | Browser microphone and minimal live UI | P0 | 2–3 h | WP 04 |
| WP 06 | Local ASR and interim/final transcript logic | P0 | 3–4 h | WP 04, WP 05, WP 00 |
| WP 07 | Two AI roles and deterministic FAQ lookup | P0 | 2–3 h | WP 06, WP 00 |
| WP 08 | Persistence of transcript and recommendations | P0 | 1–2 h | WP 03, WP 06, WP 07 |
| WP 09 | Outbox, RabbitMQ, idempotent worker | P0 | 3–4 h | WP 08 |
| WP 10 | Failure handling and minimum observability | P0 | 2–3 h | WP 06–WP 09 |
| WP 11 | Automated end-to-end verification and benchmark | P0 | 2–3 h | WP 10 |
| WP 12 | README, runbook, screencast, final review | P0 | 2–3 h | WP 11 |

These are **rough engineering estimates**, not deadlines or measured durations. Total effort may exceed one week on an underpowered machine. Preserve the priorities and use the cut list in Section 8 instead of silently weakening acceptance criteria.

## 4. Work Packages and Acceptance Criteria

### WP 01 — Create the repository foundation

**Objective:** make the project installable, testable, and reproducible before adding AI logic.

**Actions**

1. Add `pyproject.toml` with pinned compatible dependencies and a reproducible lockfile or exported constraints.
2. Create the `src/api/`, `src/worker/`, `src/api/presentation/`, `src/api/domain`, `src/api/application`, `src/api/infrastucture`, `src/knowledge/`, `tests/unit/`, and `tests/integration/` directories from the architecture document.
3. Add `.gitignore`, `.env.example`, and typed configuration with fail-fast validation for required variables.
4. Add `docker-compose.yml` with PostgreSQL and RabbitMQ bound to localhost, health checks, named volumes, and development-only credentials defined in `.env`.
5. Expose `GET /healthz` and set up logging, a Python formatter/linter, and a minimal test runner.
6. Provide standard developer commands through `Makefile` or a cross-platform script equivalent.

**Required command contract** (implement these names or document exact equivalents):

```
- Lint: `make lint`
- Test: `make test`
- Run server: `make run-api`
- Run worker: `make run-worker`
- Install deps: `make sync`
- Start db: `make db-up`
- Stop db: `make db-down`
- Migrate DB: `make migrate`
```

**Acceptance criteria**

- [ ] A fresh Python environment installs without manual source changes.
- [ ] `make infra-up` starts healthy PostgreSQL and RabbitMQ services.
- [ ] `GET /healthz` returns HTTP 200 with a lightweight response.
- [ ] `make lint` and `make test` pass on the scaffold.
- [ ] No credentials, downloaded models, database files, raw audio, or cache files are committed.
- [ ] `README.md` has a minimal prerequisites and startup section.

**Verification:** show `docker compose ps`, `curl -f http://localhost:8000/healthz`, linter output, and a passing minimal test.

### WP 02 — Define contracts and the session state machine

**Objective:** establish stable types before the WebSocket, database, and worker implementations diverge.

**Actions**

1. Define `SessionStatus` with `created`, `live`, `stopping`, `completed`, `interrupted`, and `failed` in api/domain/enums.py.
2. Define versioned Pydantic envelopes for client commands, server events, finalized utterances, agent context, recommendations, and durable domain events.
3. Implement validated transitions: `created -> live -> stopping -> completed`, plus explicit interruption and failure transitions.
4. Standardize UTC timestamps, UUIDs, monotonic per-session sequences, and millisecond audio offsets.
5. Separate transient `transcript.interim` messages from persisted `transcript.final` records.

**Deliverables:** `app/domain/events.py`, `app/domain/session.py`, `app/domain/agents.py`, `tests/unit/test_contracts.py`, `tests/unit/test_session_state.py`.

**Acceptance criteria**

- [ ] Unknown schema versions and invalid payloads fail with clear validation errors.
- [ ] Invalid state transitions are rejected without mutating the session.
- [ ] Each finalized utterance has a stable ID and sequence; interim events are explicitly transient.
- [ ] Contract models are reusable in API, persistence, and worker code, without duplicated ad hoc JSON construction.
- [ ] Unit tests cover every legal and illegal session transition.

**Verification:** `make test` plus typed serialization examples for `transcript.final` and `recommendation.created`.

### WP 03 — Implement persistence and session HTTP API

**Objective:** make authoritative session data available through PostgreSQL before streaming is introduced.

**Actions**

1. Create Alembic migrations for `sessions`, `utterances`, `recommendations`, `outbox_events`, `processed_events`, and `session_summaries`.
2. Enforce uniqueness for `(session_id, utterance_sequence)`, event IDs, and per-session summaries. Add foreign keys and useful indexes.
3. Implement a SQLAlchemy Async engine, task-scoped `AsyncSession` factory, and repository methods with explicit transaction boundaries.
4. Implement `POST /api/sessions`, `GET /api/sessions/{id}`, and `GET /api/sessions/{id}/transcript`, and `GET /api/sessions/{id}/report`.
5. Return an ordered transcript and persisted recommendations; report unknown session IDs as 404.

**Deliverables:** `api/infrastructure/storage/alembic/versions/*`, `api/infrastructure/storage/*`, `api/presentation/sessions.py`, `api/application/ports.py`, `api/application/use_cases/*`, database integration tests.

**Acceptance criteria**

- [ ] A clean database migrates to the current head and a second migration run is a no-op.
- [ ] API creates a session with `status=created` and a UUID.
- [ ] Retrieving a missing session returns 404; retrieving an existing session returns correct state.
- [ ] Transaction rollback leaves no half-written authoritative records.
- [ ] Two concurrent tasks never share the same mutable `AsyncSession`.
- [ ] Duplicate utterance keys cannot create two finalized records.

**Verification:** `make migrate`, `make test`, and HTTP requests against a local database.

### WP 04 — Build the bounded WebSocket gateway

**Objective:** establish a nonblocking audio transport and predictable session lifecycle using a fake ASR adapter.

**Actions**

1. Implement `WS /ws/sessions/{id}` with JSON commands `capture.start` and `capture.stop`, plus binary audio-frame handling.
2. Validate active session, single-user admission limit, audio frame size/format, and command ordering.
3. Use a bounded `asyncio.Queue` for audio frames and supervised receiver/processor/sender tasks.
4. Implement clean cancellation, bounded flush on stop, and `interrupted` state on disconnect.
5. Inject a fake ASR adapter that emits deterministic transcript events; never block the receive coroutine with inference.
6. Add explicit `session.overloaded` behavior instead of silently dropping source audio.

**Deliverables:** `app/api/websocket.py`, `app/services/live_session.py`, `app/audio/interfaces.py`, deterministic WebSocket tests.

**Acceptance criteria**

- [ ] A valid client can create, start, stop, and finalize a session.
- [ ] Binary frames reach the fake ASR adapter in order.
- [ ] Invalid control messages and oversized frames fail gracefully with a visible reason.
- [ ] A second concurrent live session is rejected predictably; the API remains healthy.
- [ ] Disconnect does not mark an unfinished session as `completed`.
- [ ] A deliberately slow fake processor does not freeze the event loop or grow the queue without bound.

**Verification:** automated WebSocket integration test using deterministic PCM bytes, plus a queue-overflow test.

### WP 05 — Implement browser audio capture and basic UI

**Objective:** show live input and server events with no frontend framework or cloud dependency.

**Actions**

1. Create a page with Start, Stop, connection state, transcript panel, recommendation panel, and error display.
2. Capture microphone audio with `getUserMedia` and `AudioWorklet`. Convert the actual input sample rate to the configured server format (initially mono 16 kHz PCM16).
3. Send binary frames at a bounded cadence. Keep command messages as JSON.
4. Distinguish replaceable interim transcript text from immutable final utterances by `utterance_id` and sequence.
5. Handle permission denial, socket closure, model errors, overload, and stop-in-progress states without browser crashes.
6. Display basic elapsed session time and latency timestamps when available.

**Deliverables:** `web/index.html`, `web/app.js`, `web/audio-worklet.js`, minimal CSS.

**Acceptance criteria**

- [ ] A user can grant microphone permission on localhost and see the live state.
- [ ] Start and Stop work without a page reload.
- [ ] Fake interim text is updated in place; each finalized utterance appears once.
- [ ] Permission denial and lost WebSocket display helpful errors and re-enable controls appropriately.
- [ ] Browser console shows no unhandled exception during the happy path.

**Verification:** manual Chromium test with fake ASR; screenshot is optional and not a release artifact.

### WP 06 — Connect local ASR and utterance finalization

**Objective:** replace the fake adapter in the runtime path while preserving deterministic tests.

**Actions**

1. Implement `faster-whisper` initialization as a replaceable adapter with configurable model, device, compute type, and language.
2. Add a lightweight VAD/utterance assembler that generates interim analysis windows and finalizes after a silence threshold or maximum utterance length.
3. Run CPU/GPU-bound ASR outside the asyncio WebSocket receive task using a bounded executor or equivalent controlled worker.
4. Prevent obsolete interim results from replacing a newer final transcript. Deduplicate overlapping text between audio windows.
5. Keep model initialization out of individual requests; surface model-loading failures through readiness/error state.
6. Add a reproducible WAV fixture test and a real inference smoke script.

**Deliverables:** `app/audio/vad.py`, `app/audio/asr_faster_whisper.py`, `app/audio/utterance_assembler.py`, ASR unit tests and smoke test.

**Acceptance criteria**

- [ ] Local spoken audio produces at least one finalized transcript without any remote inference call.
- [ ] At least one interim update is observable for a sufficiently long utterance on the reference machine; if not, FR 03 remains unverified and must be reported as a release blocker.
- [ ] Each final utterance is emitted once with stable timing, sequence, and ID.
- [ ] Pure-silence input does not produce a fabricated final utterance.
- [ ] The WebSocket remains responsive while the ASR model is running.
- [ ] Invalid audio or model errors produce an error event; no false `transcript.final` is emitted.
- [ ] Fake-ASR unit tests pass independently of locally downloaded model files.

**Verification:** `make test`, `make smoke` with a consented fixture, and an event-loop responsiveness test using a slow adapter.

### WP 07 — Implement local AI analysis and FAQ grounding

**Objective:** produce a useful action from real finalized speech with predictable and testable outputs.

**Actions**

1. Create `knowledge/faq.json` with 5–10 short entries, including duplicate API notifications, event retries, and idempotency; give every entry a stable ID.
2. Implement `ContextAgent`: short issue, intent, confidence, and insufficient-context outcome.
3. Implement deterministic FAQ candidate selection; no embeddings, network retrieval, or vector database.
4. Implement `RecommendationAgent`: actionable next step, brief rationale, zero or more known FAQ IDs, and uncertainty fallback.
5. Use a shared local llama.cpp model through an async HTTP client. Validate responses with Pydantic, apply timeouts, and cap context length/output tokens.
6. Prevent prompt text or speech transcription from causing tool execution, shell commands, or edits. Agents return suggestions only.
7. Debounce recommendation requests and discard outdated responses when a newer context version has superseded them.

**Deliverables:** `app/agents/context.py`, `app/agents/recommendation.py`, `app/agents/llama_cpp.py`, `app/services/faq.py`, `knowledge/faq.json`, tests.

**Acceptance criteria**

- [ ] A mocked duplicate-notification transcript produces a structured issue and a relevant next-step recommendation.
- [ ] Any returned FAQ ID exists in the seeded knowledge base; invented IDs are rejected.
- [ ] An unrelated or ambiguous statement produces an explicit uncertainty/diagnostic fallback.
- [ ] Invalid model JSON, timeout, or model-unavailable errors do not crash the live session.
- [ ] Stale analysis results cannot overwrite a newer recommendation.
- [ ] Runtime inference uses only the configured local model endpoint; automated tests use a fake endpoint.

**Verification:** unit tests using fixed LLM responses, plus one manual local llama.cpp smoke test with the seeded scenario.

### WP 08 — Wire authoritative writes into the live path

**Objective:** make the UI and HTTP API agree on committed transcript and recommendation records.

**Actions**

1. On final utterance, commit the utterance and an associated outbox event together, then publish `transcript.final` over the WebSocket.
2. On validated recommendation, commit its record and associated outbox event together, then publish `recommendation.created` over the WebSocket.
3. Implement idempotent upserts or unique-key conflict handling for repeated finalization attempts.
4. Return persisted utterances and recommendations through the transcript HTTP endpoint in stable sequence order.
5. Never send a success-looking authoritative final event when its database transaction failed.

**Deliverables:** session service transaction methods, repository updates, integration tests.

**Acceptance criteria**

- [ ] After a completed conversation, HTTP retrieval matches the final transcript displayed in the browser.
- [ ] One utterance/recommendation results in one authoritative database row and one corresponding outbox record.
- [ ] Replaying the same finalization input leaves row counts unchanged.
- [ ] Database failure produces a visible persistence error, not a fake success.
- [ ] Interim ASR results do not appear in the authoritative transcript table.

**Verification:** a real PostgreSQL test that replays the same final event twice and checks both API output and database uniqueness.

### WP 09 — Implement RabbitMQ outbox and idempotent worker

**Objective:** demonstrate reliable background processing without placing RabbitMQ on the low-latency path.

**Actions**

1. Add an outbox publisher supervised by the API process. Poll unpublished events, publish persistent messages to a durable exchange/queue, and use publisher confirms.
2. Mark `published_at` only after confirmation. Keep failed rows eligible for retry and expose pending counts.
3. Add a worker with manual acknowledgements and bounded prefetch. Commit effects and `processed_events` key before acknowledging.
4. Handle `session.completed` with a simple idempotent post-session result (for example, a short stored summary or processing record). Do not make the live transcript depend on this output.
5. Configure bounded retry/backoff and a dead-letter route for repeated processing failures. Prevent unbounded redelivery loops.
6. Add restart tests: publisher after commit-before-confirm, duplicate delivery, worker shutdown with a backlog, and RabbitMQ temporarily unavailable.

**Deliverables:** `app/messaging/outbox_publisher.py`, `app/messaging/broker.py`, `worker/main.py`, broker configuration, integration tests.

**Acceptance criteria**

- [ ] A completed session creates durable domain events and the worker processes them.
- [ ] Stopping the worker does not stop WebSocket transcription or recommendation generation.
- [ ] Queue depth increases during a worker outage, then drains after restart.
- [ ] Processing the same event twice yields one processed-event effect and one stored summary/record.
- [ ] A broker outage leaves outbox rows unpublished and recoverable; no committed session data is lost.
- [ ] A crash after publish confirmation but before `published_at` commit is safe to retry.
- [ ] The consumer acknowledges only after successful database commit.

**Verification:** `make test` with explicit worker stop/restart and database row-count assertions. Record the failure-injection commands in `docs/demo-runbook.md`.

### WP 10 — Add observability and controlled failure behavior

**Objective:** make latency and failure modes visible without overbuilding a monitoring stack.

**Actions**

1. Implement structured JSON logs with UTC timestamp, `session_id`, `correlation_id`, event name, latency, and error category.
2. Implement `GET /readyz` with separate dependency statuses; never treat a failed local model as fully ready.
3. Export useful metrics from `GET /metrics`: active sessions, audio queue depth, ASR latency, recommendation latency, LLM failures, pending outbox events, and worker outcomes.
4. Add timeouts and consistent exception mapping for ASR, LLM, database, WebSocket, and broker operations.
5. Ensure cleanup on stop, disconnect, and process shutdown: no orphan per-session tasks or unbounded in-memory buffers.
6. Keep raw audio and full transcripts out of routine logs; expose sensitive data only through the local application endpoints.

**Deliverables:** `app/observability/*`, readiness endpoint, failure-handling tests, optional Prometheus scrape config.

**Acceptance criteria**

- [ ] Every final ASR and recommendation event has measurable elapsed time and a session correlation ID.
- [ ] Metrics update after a real or fake session and distinguish successes from failures.
- [ ] Stopping llama.cpp or making the fake LLM time out leaves the transcript accessible.
- [ ] Disconnecting the browser closes/cancels session tasks without leaking active-session count.
- [ ] Logs contain no raw audio bytes, secrets, or full transcript by default.
- [ ] The API remains responsive while background delivery is delayed.

**Verification:** inspect `/metrics`, `/readyz`, and logs during a normal run and at least two injected failures.

### WP 11 — Run end-to-end tests and latency evaluation

**Objective:** prove the entire workflow against both deterministic fixtures and real local models.

**Actions**

1. Build an automated scripted fixture that exercises session creation, WebSocket audio streaming, final transcript, recommendation, persistence, and session close with fake inference.
2. Add tests for invalid frames, silence, duplicate final events, stale agent outputs, database rollback, worker retry, and consumer restart.
3. Run an actual local audio/LLM scenario and record durations on the reference machine.
4. For p95 reporting, use a repeatable set of at least 30 utterance/result samples when feasible; specify sample count, language, input length, machine, and models. Do not mix mock timings with real timings.
5. Compare measurements with provisional PRD targets: p95 final transcript within 5 seconds of utterance end; p95 recommendation within 10 seconds of final transcript.

**Deliverables:** `tests/e2e/*` or `tests/integration/test_demo_flow.py`, `docs/benchmark-results.md`, repeatable fixture and test commands.

**Acceptance criteria**

- [ ] `make verify` passes locally.
- [ ] Deterministic E2E flow completes without cloud calls or external user accounts.
- [ ] One real microphone or replayed-audio session reaches a real local ASR transcript and real local LLM recommendation.
- [ ] Database contains exactly one final record per utterance after retry scenarios.
- [ ] Test failures are actionable: they show which stage, event, or assertion failed.
- [ ] Benchmark document includes actual p50/p95 where sample size supports it, hardware details, and any unmet targets.

**Verification:** save command output and benchmark report in the final handoff. A failed latency target is a documented performance limitation, not permission to misrepresent results.

### WP 12 — Complete the demo package and handoff

**Objective:** make the repository understandable and convincing to a technical interviewer in under five minutes.

**Actions**

1. Write `README.md` with purpose, setup, model provisioning, commands, UI instructions, troubleshooting, and known limitations.
2. Keep `ARCHITECTURE.md`, PRD, and this plan in the repository; update them only for intentional and documented design changes.
3. Create `docs/demo-runbook.md`: scripted duplicate-notification conversation, expected UI states, worker stop/restart commands, and recovery checks.
4. Make a 3–4 minute screencast with visible microphone input, incremental transcript, grounded recommendation, saved result, one observability/failure scene, and a concise code/architecture walkthrough.
5. Include a fallback prerecorded fixture for demos where microphones or permissions are unreliable; label it as prerecorded audio.
6. Review the final changes for secrets, temporary files, binary models, unused dependencies, and broken links.

**Deliverables:** `README.md`, `docs/demo-runbook.md`, screencast file or shareable link, final acceptance report.

**Acceptance criteria**

- [ ] A developer can follow the README on the reference OS without unstated manual setup steps.
- [ ] All P0 work packages have passing evidence or a visible, accurately described blocker.
- [ ] The screencast is 3–4 minutes and uses real local inference for the core AI flow.
- [ ] The screencast does not conceal failures or present mock results as live results.
- [ ] The worker-failure demo shows recovery and checks duplicate-effect count, not only queue movement.
- [ ] The handoff includes what is implemented, tests run, measured latency, limitations, and next steps.

**Verification:** replay the exact runbook once from a fresh process start, then review the recording and repository state.

## 5. Requirements Traceability

| PRD requirement | Implemented in | Required proof |
| --- | --- | --- |
| FR 01 Session start and stop | WP 02, WP 03, WP 04, WP 05 | State-machine unit test and browser smoke test |
| FR 02 Binary streaming and disconnect | WP 04, WP 05 | WebSocket binary-frame and disconnect tests |
| FR 03 Interim/final transcript | WP 06, WP 08 | Deduplication tests and real local ASR smoke |
| FR 04 Context extraction | WP 07 | Fixed-response unit tests and real-model smoke |
| FR 05 Grounded recommendation | WP 07 | FAQ ID validation and insufficient-evidence fallback |
| FR 06 Session persistence | WP 03, WP 08 | SQL integration tests and HTTP retrieval |
| FR 07 RabbitMQ and duplicates | WP 09 | Worker-restart and duplicate-delivery tests |
| FR 08 User-visible failures | WP 04, WP 05, WP 06, WP 07, WP 10 | Permission, ASR, LLM, and DB failure tests |
| FR 09 Observability | WP 10 | `/metrics`, `/readyz`, and structured log checks |
| FR 10 Replayed demo fixture | WP 11, WP 12 | Deterministic E2E replay and labeled screencast fallback |

The PRD marks FR 09 and FR 10 as **Should**. The plan includes a minimal version of both because observability and demo reliability materially support the hiring objective. Their advanced forms remain optional.

## 6. Definition of Done

A work package is complete only if all of the following apply:

- [ ] Its implementation matches the stated domain and service boundaries.
- [ ] Its P0 acceptance criteria are verified with tests or an explicit reproducible manual check.
- [ ] Relevant negative/error cases are covered; a successful happy-path screenshot alone is insufficient.
- [ ] The standard linter and applicable unit/integration tests pass.
- [ ] Configuration is documented; secrets, raw recordings, and downloaded models are not committed.
- [ ] No known regression has been concealed by disabling a test or replacing a real path with a fake one.
- [ ] The work log names exact commands, results, remaining limitations, and changed files.

**Project release gate:** all FR 01–FR 08 criteria pass, the live inference path has been demonstrated locally, the worker restart is idempotent, the README is reproducible, and a real screencast is available. FR 09/FR 10 should have at least their minimum implementations, and unmet latency targets must be documented.

## 7. Final Acceptance Checklist

Then perform the manual sequence:

1. Start API, worker, and local model runtime. Open the local browser UI.
2. Speak or replay a support conversation about duplicate notifications.
3. Observe an interim transcript, one finalized utterance, a grounded recommendation, and no duplicate transcript text.
4. Stop the session and confirm the same finalized data through the HTTP API.
5. Stop the worker, complete a second session, then restart the worker. Verify that backlog drains and the database contains one completed background effect per event.
6. Interrupt llama.cpp or simulate timeout and confirm that transcripts still work while recommendations fail visibly and safely.
7. Open `/healthz`, `/readyz`, and `/metrics`; review logs for error details without sensitive audio content.
8. Run the demo runbook from start to finish while recording the screencast.

## 8. Timebox and Scope Cut Rules

If time is running short, preserve the highest-value sequence: **microphone → WebSocket → real ASR → local AI recommendation → persisted transcript**. Do not trade that working path for architectural extras.

1. **First cuts:** visual animation, advanced dashboards, extra FAQ entries, LLM-generated session summaries, and automated browser screenshots.
2. **Next cuts:** additional model choices, sophisticated VAD tuning, complex inference streaming, and unnecessary service decomposition. Keep clear adapters and basic error handling.
3. **Never cut without documenting the scope change:** input validation, bounded audio queue, data integrity, idempotent event effects, tests for critical failure cases, and honest performance reporting.
4. If a P0 requirement cannot be completed within the agreed timebox, stop adding features. Record a blocker, narrow the implementation only with explicit approval, and label the final demo accordingly.

## 9. Agent Progress and Final Report Format

After each work package, report:

```text
Work package: WP XX — <name>
Status: complete | blocked | partial
Changed files: <paths>
Implemented: <concrete behavior>
Verification: <commands and pass/fail results>
Manual checks: <what was observed, if any>
Known limitations: <none or explicit list>
Next: WP YY — <name>
```

At final handoff, provide:

1. A concise feature list mapped to FR 01–FR 10.
2. Exact local setup and launch commands.
3. Test results and any missing test coverage.
4. Benchmarked p50/p95 results with hardware, model names, and sample counts.
5. Screencast location and reproducible demo runbook.
6. Known defects, tradeoffs, and recommended follow-up work.

**No acceptance criterion may be marked as passed solely because code was written. It must be observed, tested, or explicitly called unverified.**

## 10. Reference Documentation

- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [RabbitMQ publisher confirms and consumer acknowledgements](https://www.rabbitmq.com/docs/confirms)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [Python asyncio queues](https://docs.python.org/3/library/asyncio-queue.html)
- [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)
