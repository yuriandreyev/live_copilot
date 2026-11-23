# Live AI Copilot release handoff

[Watch the 3:15 screencast](../demo/live-copilot-demo.mp4) ·
[Run the demo from a fresh start](demo-runbook.md) ·
[Architecture](ARCHITECTURE.md) · [PRD](Live_AI_Copilot_PRD.md)

The recording uses a prerecorded synthetic English support dialogue as
Chromium's microphone input. The browser AudioWorklet, faster-whisper ASR,
llama.cpp, PostgreSQL, RabbitMQ, and the worker ran during capture. The video
includes the synthetic input audio. The database and queue were isolated for
the recording. No physical microphone was used in this run.

## Observed on the reference machine

- Chromium showed two interim updates, one committed transcript, and one
  recommendation for each of the two captured sessions. The recommendation
  cited `duplicate-notifications` and suggested comparing event IDs and
  delivery attempts before checking consumer deduplication.
- The transcript endpoint returned the same recommendation ID and recorded
  utterance. The first report showed one final utterance and one recommendation.
- Capture remained available while the worker process was stopped. The
  queue showed two ready messages when sampled and the report was empty. After
  restart the queue drained and the second report appeared.
- A deliberate redelivery of the second session's completion event incremented
  the duplicate counter to one. PostgreSQL still contained one processed
  marker for that event ID and one summary for the session.
- The ASR transcript rendered the last word of the synthetic dialogue as
  “cost” instead of “cause.” The duplicate-notification issue was preserved.

| Recorded observation | Seconds |
| --- | ---: |
| Estimated speech end to first session's transcript commit | 1.99 |
| First session's transcript commit to recommendation commit | 4.90 |

These are server-side observations for one illustrated session on macOS
26.5.2 (arm64), using faster-whisper `small` on CPU int8 and
`Forge-1-E2B-Q4_K_M.gguf` through llama.cpp. WP11 was skipped by request,
so benchmark percentiles and the provisional p95 targets remain unverified.

## Requirements and evidence

| Requirement | Evidence |
| --- | --- |
| FR 01 Capture lifecycle | Chromium start, live, stop, and completion states |
| FR 02 Audio transport | Browser AudioWorklet and WebSocket capture, with disconnect handling in automated tests |
| FR 03 Interim and final transcript | Two interim updates and one final record per recorded session |
| FR 04 Context extraction | Real context analysis during both recordings and fixed-response agent tests |
| FR 05 Grounded recommendation | Real FAQ citation in both sessions, with fallback and citation validation tests |
| FR 06 Persistence | HTTP readback and transaction rollback tests |
| FR 07 Durable background processing | Real worker outage, restart, and redelivery with database row counts |
| FR 08 Visible failures | Permission, ASR, LLM, database, and broker failure coverage |
| FR 09 Observability | Readiness, metrics, latency logs, and replay counter |
| FR 10 Prerecorded fallback | [Synthetic fixture generator](../demo/generate-fixture.sh) and [local playback helper](../demo/prerecorded-input.js) |

WP05–WP10 have passing work-package records. The full suite exercises the
foundation, contracts, storage, and WebSocket behavior from WP01–WP04.
Standalone package acceptance records for WP00–WP04 are incomplete.
WP11 remains open by request. Physical microphone capture was not part of
the recorded validation.

## Reproduce the checks

The WP12 gate passed all 115 Python tests and three browser audio tests.
Starlette emitted the existing AnyIO deprecation warning. The recording's
video, audio track, and local documentation links passed verification.

Start the services with `make infra-up`, then run `make verify`. Run the
three browser conversion checks with
`node --test tests/web/audio-worklet.test.cjs`. To check the recording's
duration, audio track, and local documentation links, run
`UV_CACHE_DIR=.uv-cache uv run --locked --no-sync python demo/verify_recording.py`.

For the next release review, run the physical-microphone walkthrough and the
WP11 latency benchmark if those release gates are required.
