const element = (id) => document.getElementById(id);
const startButton = element("start");
const stopButton = element("stop");
const status = element("status");
const elapsed = element("elapsed");
const error = element("error");
const interim = element("interim");
const transcript = element("transcript");
const transcriptEmpty = element("transcript-empty");
const timing = element("transcript-timing");
const recommendations = element("recommendations");
const recommendationsEmpty = element("recommendations-empty");

const BUFFER_LIMIT = 3_200 * 10;
let capture;
let state = "idle";

function setState(next, label) {
  state = next;
  status.dataset.state = next;
  status.textContent = label;
  startButton.disabled = ["connecting", "live", "stopping"].includes(next);
  stopButton.disabled = next !== "live";
}

function updateClock(run) {
  if (run.startedAt === undefined) return;
  const seconds = Math.floor((performance.now() - run.startedAt) / 1000);
  elapsed.textContent = [Math.floor(seconds / 60), seconds % 60]
    .map((part) => String(part).padStart(2, "0")).join(":");
}

function releaseMicrophone(run) {
  run.stream?.getTracks().forEach((track) => track.stop());
  run.source?.disconnect();
  run.source = undefined;
  if (run.worklet) {
    run.worklet.port.onmessage = null;
    run.worklet.disconnect();
    run.worklet = undefined;
  }
  if (run.context && run.context.state !== "closed") {
    void run.context.close().catch(() => {});
  }
}

function finish(run, message) {
  if (capture !== run) return;
  capture = undefined;
  updateClock(run);
  clearInterval(run.clock);
  clearTimeout(run.deadline);
  releaseMicrophone(run);
  run.socket?.close();
  interim.hidden = true;
  transcriptEmpty.hidden = transcript.childElementCount > 0;
  error.hidden = !message;
  error.textContent = message ?? "";
  setState(message ? "failed" : "completed", message ? "Capture ended" : "Completed");
}

function sendCommand(run, eventType) {
  run.socket.send(JSON.stringify({
    schema_version: 1,
    session_id: run.id,
    event_type: eventType,
  }));
}

function showRecommendation(payload) {
  const row = document.createElement("li");
  const action = document.createElement("strong");
  action.textContent = payload.action;
  const rationale = document.createElement("div");
  rationale.textContent = payload.rationale;
  row.append(action, rationale);
  recommendations.append(row);
  recommendationsEmpty.hidden = true;
}

function handleEvent(run, event) {
  if (event.schema_version !== 1 || event.session_id !== run.id ||
      !Number.isSafeInteger(event.sequence) || event.sequence <= run.sequence) return;
  run.sequence = event.sequence;
  const payload = event.payload;

  switch (event.event_type) {
    case "session.status":
      if (payload.status === "live" && state === "connecting") {
        clearTimeout(run.deadline);
        run.startedAt = performance.now();
        run.clock = setInterval(() => updateClock(run), 250);
        run.source.connect(run.worklet).connect(run.context.destination);
        setState("live", "Live");
      } else if (payload.status === "stopping" && state === "live") {
        setState("stopping", "Stopping…");
      }
      break;
    case "transcript.interim":
      transcriptEmpty.hidden = true;
      interim.hidden = false;
      interim.textContent = payload.text;
      break;
    case "transcript.final": {
      interim.hidden = true;
      if (run.utterances.has(payload.utterance_id)) break;
      run.utterances.add(payload.utterance_id);
      const row = document.createElement("li");
      row.textContent = payload.text;
      transcript.append(row);
      transcriptEmpty.hidden = true;
      const timestamp = new Date(event.occurred_at);
      if (Number.isFinite(timestamp.getTime())) {
        const clock = document.createElement("time");
        clock.dateTime = timestamp.toISOString();
        clock.textContent = timestamp.toLocaleTimeString();
        timing.replaceChildren(
          `Audio ended at ${(payload.end_ms / 1000).toFixed(1)} s · Final event at `, clock,
        );
        timing.hidden = false;
      }
      break;
    }
    case "recommendation.created":
      showRecommendation(payload);
      break;
    case "session.completed":
      finish(run);
      break;
    case "session.error":
    case "session.overloaded":
      finish(run, payload.message || "The server ended capture. Try starting again.");
      break;
  }
}

async function start() {
  if (capture) return;
  const run = { sequence: 0, utterances: new Set() };
  capture = run;
  setState("connecting", "Connecting…");
  for (const panel of [transcript, recommendations, interim, timing]) panel.replaceChildren();
  for (const panel of [interim, timing, error]) panel.hidden = true;
  transcriptEmpty.hidden = false;
  recommendationsEmpty.hidden = false;
  elapsed.textContent = "00:00";

  let failure = "Could not access the microphone. Check browser permissions and try again.";
  try {
    if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
      finish(run, "Microphone capture requires Chromium and a secure origin such as localhost.");
      return;
    }
    run.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
    failure = "Could not start browser audio capture. Try starting again.";
    run.context = new AudioContext();
    await run.context.resume();
    await run.context.audioWorklet.addModule("/audio-worklet.js");
    run.source = run.context.createMediaStreamSource(run.stream);
    run.worklet = new AudioWorkletNode(run.context, "pcm-capture");
    run.worklet.onprocessorerror = () => finish(run, "Browser audio processing failed. Try starting again.");
    run.worklet.port.onmessage = ({ data }) => {
      if (capture !== run) return;
      if (data === "stopped") {
        releaseMicrophone(run);
        if (run.socket?.readyState === WebSocket.OPEN) sendCommand(run, "capture.stop");
      } else if (run.socket?.readyState === WebSocket.OPEN && data instanceof ArrayBuffer) {
        if (run.socket.bufferedAmount + data.byteLength > BUFFER_LIMIT) {
          finish(run, "The connection could not keep up with microphone audio. Try starting again.");
        } else {
          run.socket.send(data);
        }
      }
    };

    failure = "Could not create a session. Check that the server and PostgreSQL are running.";
    const response = await fetch("/api/sessions", {
      method: "POST",
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) throw new Error("Session creation failed");
    ({ session_id: run.id } = await response.json());

    failure = "Could not connect to live capture. Check that the server is running.";
    const url = new URL(`/ws/sessions/${encodeURIComponent(run.id)}`, location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    run.socket = new WebSocket(url);
    run.deadline = setTimeout(() => finish(run, "Live capture did not connect in time. Try starting again."), 12_000);
    run.socket.onopen = () => {
      if (capture === run) sendCommand(run, "capture.start");
    };
    run.socket.onmessage = ({ data }) => {
      if (capture !== run) return;
      try {
        handleEvent(run, JSON.parse(data));
      } catch {
        finish(run, "The server sent an invalid capture update. Try starting again.");
      }
    };
    run.socket.onerror = () => finish(run, "Live capture lost its connection to the server.");
    run.socket.onclose = () => finish(run, "Live capture disconnected before completing. Try starting again.");
  } catch (cause) {
    if (cause?.name === "NotAllowedError" && !run.stream) {
      failure = "Microphone access was denied. Allow it in your browser and try again.";
    }
    finish(run, failure);
  }
}

function stop() {
  if (state !== "live" || !capture) return;
  const run = capture;
  setState("stopping", "Stopping…");
  run.deadline = setTimeout(() => finish(run, "Capture did not stop in time. Try starting again."), 8_000);
  run.worklet.port.postMessage("stop");
}

startButton.addEventListener("click", start);
stopButton.addEventListener("click", stop);
