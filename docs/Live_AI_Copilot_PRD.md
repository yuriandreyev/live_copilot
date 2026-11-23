# Live AI Copilot Product Requirements Document

*Version 1.0 · 18 November 2026 · Local MVP · Target build time 5 to 7 evenings*

## Product Overview

Live AI Copilot is a locally deployed assistant for support-style conversations. It captures microphone audio in a browser, produces an incremental transcript, identifies customer issues, and suggests actionable responses while a conversation is in progress. The MVP demonstrates asynchronous Python backend design, local AI inference, event-driven processing, and observable failure handling in a reproducible technical demo.

Decision: deliver one convincing end-to-end workflow with a short screencast and a runnable repository. The initial release is single-user and local-only; it is not a production contact-center product.

## Problem and Target User

During a technical support conversation, an operator must listen, capture details, identify likely causes, and consult guidance at the same time. A lightweight copilot can surface a usable transcript and timely suggestions without interrupting the conversation.

Primary user: a technical support operator handling an API integration issue. Secondary user: an engineering interviewer evaluating the service architecture, reliability, and code quality.

## Goals and Success Measures

| **Goal**              | **MVP success measure**                                                                                                     |
|-----------------------|-----------------------------------------------------------------------------------------------------------------------------|
| Live user value       | A five-minute sample conversation produces readable finalized transcript segments and at least one relevant recommendation. |
| Technical credibility | The code exposes explicit async boundaries, message schemas, idempotent consumers, and automated tests.                     |
| Local operation       | After model provisioning, services start from documented commands and work without paid AI APIs.                            |
| Demo readiness        | A three- to four-minute screencast shows the complete flow, including observed timings and error handling.                  |

## User Workflow

1.  The operator opens the local web app, reviews the microphone permission prompt, and starts a session.

2.  The browser streams audio frames to a FastAPI WebSocket endpoint; speech recognition emits interim and final transcript updates.

3.  Once an utterance is finalized, a Context Agent detects the issue and the Recommendation Agent proposes a next step using a small seeded knowledge base.

4.  The interface displays the suggestion next to the transcript. The operator can continue speaking, then end the session.

5.  The completed session, final transcript, and proposed actions remain available for review.

## MVP Scope

### Included

- Single active local session; browser microphone capture and WebSocket event feed.

- Local chunk-based speech recognition with an explicit interim-versus-final transcript state.

- Two specialized AI roles using a shared local LLM; knowledge grounded in a small static FAQ.

- Async persistence in PostgreSQL and durable background event processing with RabbitMQ.

- Minimal observability, structured logging, automated tests, and Docker Compose setup.

### Excluded

Authentication, multi-tenant accounts, speaker diarization, multilingual translation, telephony integrations, vector search, Kubernetes, Consul, Vault, public hosting, and guaranteed production service-level agreements.

## Functional Requirements

| **ID** | **Priority** | **Requirement and acceptance criteria**                                                                                                                     |
|--------|--------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| FR 01  | Must         | The operator can start and stop a session. The UI clearly indicates connecting, live, stopping, and completed states.                                       |
| FR 02  | Must         | The browser sends microphone audio over WebSocket. The server accepts bounded audio frames and closes a session cleanly on disconnect.                      |
| FR 03  | Must         | Speech recognition emits interim and final utterance events. Final transcript events have stable identifiers and appear only once in the UI.                |
| FR 04  | Must         | The Context Agent extracts a short issue statement and relevant intent from a finalized utterance or updated conversation context.                          |
| FR 05  | Must         | The Recommendation Agent returns a concise next action, with a knowledge-base reference when applicable and a clear fallback when evidence is insufficient. |
| FR 06  | Must         | The system stores session metadata, finalized transcript segments, and recommendations. A completed session can be retrieved by ID.                         |
| FR 07  | Must         | A background consumer receives durable events through RabbitMQ. Duplicate delivery does not create duplicate persisted records.                             |
| FR 08  | Must         | User-visible errors are explicit when microphone, ASR, or LLM processing fails; the application remains responsive.                                         |
| FR 09  | Should       | A basic metrics endpoint reports active sessions, ASR/LLM duration, event processing errors, and queue backlog where exposed.                               |
| FR 10  | Should       | A prerecorded audio fixture can replay the same scripted demo for reliable evaluation without a live microphone.                                            |

## Architecture and Data Flow

The low-latency path is direct: browser audio → FastAPI WebSocket gateway → bounded speech recognition worker → final utterance → agent orchestrator → WebSocket UI update. The RabbitMQ path carries background domain events, not raw audio frames.

| **Component**   | **Responsibility**                                                         | **Proposed implementation**      |
|-----------------|----------------------------------------------------------------------------|----------------------------------|
| Web UI          | Capture audio; display transcript, status, and suggested actions.          | Plain HTML and JavaScript        |
| API gateway     | Manage sessions, WebSockets, outbound events, and request validation.      | FastAPI and asyncio              |
| ASR adapter     | Voice activity detection, chunk transcription, and utterance finalization. | faster-whisper; selectable model |
| AI orchestrator | Coordinate Context and Recommendation agents with bounded concurrency.     | Python async tasks; llama.cpp API |
| Data layer      | Persist session state, final segments, and actions.                        | PostgreSQL and SQLAlchemy Async  |
| Event worker    | Process durable domain events with retry and idempotency.                  | RabbitMQ; Python consumer        |

### Suggested Event Contract

Each event carries event_id, session_id, sequence_number, event_type, occurred_at, and payload. Initial types are transcript.interim, transcript.final, analysis.completed, recommendation.created, and session.completed. Include a schema version, correlation ID, and stable utterance ID. Only finalized data is persisted as an authoritative transcript.

Session, utterance, and recommendation IDs are generated server-side. A unique event_id or domain key supports idempotent writes. Each concurrent database task uses its own AsyncSession.

## Nonfunctional Requirements

| **Area**     | **Target or required behavior**                                                                                                                                                                                    |
|--------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Latency      | Provisional targets on the reference machine: p95 final transcript within 5 seconds after utterance end; p95 recommendation within 10 seconds after final transcript. Publish measured results and hardware specs. |
| Concurrency  | Support one sustained microphone session without UI blocking; use bounded queues and explicit overload behavior.                                                                                                   |
| Reliability  | Gateway remains usable when the background consumer is down; queued durable events are processed after recovery. LLM failure does not destroy the transcript.                                                      |
| Data privacy | Run inference locally. Request microphone consent. Do not retain raw audio by default. Bind services to localhost unless explicitly configured otherwise.                                                          |
| Operations   | Provide health checks, structured logs with session correlation, configuration through environment variables, and documented restart behavior.                                                                     |
| Testing      | Unit tests for transcript state and agents; integration tests for persistence and duplicate events; a WebSocket smoke test.                                                                                        |

## Delivery Plan

| **Day** | **Deliverable**                                                          |
|---------|--------------------------------------------------------------------------|
| 1       | Repository scaffold, minimal UI, WebSocket lifecycle, audio capture.     |
| 2       | Local ASR adapter, utterance finalization, streaming transcript display. |
| 3       | Local LLM integration, Context Agent, Recommendation Agent, small FAQ.   |
| 4       | PostgreSQL models, RabbitMQ events, worker and idempotency.              |
| 5       | Tests, error paths, latency measurements, minimal metrics.               |
| 6 to 7  | Stabilization, README, architecture notes, demo fixture, screencast.     |

## Demo and Release Acceptance

The release is accepted when all Must requirements work on the documented reference machine and the following script completes:

- Launch local dependencies and application; show health and metrics endpoints.

- Start a support conversation about duplicate API notifications; show incremental transcript updates.

- Show the detected issue and a specific actionable recommendation tied to the seeded FAQ.

- Stop the session; retrieve its persisted transcript and recommendation.

- Stop and restart the background worker; demonstrate queued-event recovery without duplicate final records.

- Show one automated test and recorded latency measurements; finish with repository structure and architecture tradeoffs.

Delivery artifacts: source repository, Docker Compose configuration, model setup instructions, README, automated tests, architecture note, and a three- to four-minute screencast.

## Risks and Mitigations

| **Risk**                                  | **Mitigation**                                                                                                                            |
|-------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| Local hardware cannot meet latency target | Benchmark ASR and LLM on day 1; choose smaller quantized models and shorten response output. Treat targets as provisional until measured. |
| Transcript repetition or unstable chunks  | Use explicit interim/final state, stable utterance IDs, overlap filtering, and deterministic replay tests.                                |
| Agent output is inaccurate                | Restrict to a narrow seeded scenario; surface uncertainty and cite the relevant FAQ item rather than inventing answers.                   |
| Scope exceeds one week                    | Protect the live transcript and recommendation path; treat advanced dashboards and fault-injection polish as optional.                    |

## Open Decisions

- Reference development hardware and operating system, especially GPU and available memory.

- Primary spoken language for the demo; choose the ASR model accordingly.

- Final local LLM size after an early latency benchmark.
