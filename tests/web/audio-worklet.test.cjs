const assert = require("node:assert/strict");
const fs = require("node:fs");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync("web/audio-worklet.js", "utf8");

for (const sampleRate of [16_000, 44_100, 48_000]) {
  test(`produces little-endian, mono PCM16 at 16 kHz from ${sampleRate} Hz`, () => {
    const messages = [];
    let Processor;
    vm.runInNewContext(source, {
      sampleRate,
      AudioWorkletProcessor: class {
        port = { postMessage: (message) => messages.push(message) };
      },
      registerProcessor: (_, implementation) => { Processor = implementation; },
    });
    const worklet = new Processor();
    for (let offset = 0; offset < sampleRate / 4; offset += 128) {
      const size = Math.min(128, sampleRate / 4 - offset);
      worklet.process([[new Float32Array(size).fill(1), new Float32Array(size)]]);
    }
    worklet.port.onmessage({ data: "stop" });

    assert.deepEqual(messages.slice(0, -1).map((frame) => frame.byteLength), [3200, 3200, 1600]);
    assert.equal(messages.at(-1), "stopped");
    for (const frame of messages.slice(0, -1)) {
      const view = new DataView(frame);
      for (let i = 0; i < view.byteLength; i += 2) {
        assert.equal(view.getInt16(i, true), 16384);
      }
    }
  });
}
