const TARGET_RATE = 16_000;
const FRAME_SAMPLES = TARGET_RATE / 10;

class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.remaining = sampleRate;
    this.weightedSum = 0;
    this.frame = new ArrayBuffer(FRAME_SAMPLES * 2);
    this.view = new DataView(this.frame);
    this.length = 0;
    this.stopped = false;
    this.port.onmessage = ({ data }) => {
      if (data === "stop" && !this.stopped) {
        this.stopped = true;
        if (this.length) this.sendFrame(this.frame.slice(0, this.length * 2));
        this.port.postMessage("stopped");
      }
    };
  }

  sendFrame(frame) {
    this.port.postMessage(frame, [frame]);
  }

  process(inputs) {
    if (this.stopped) return false;
    const channels = inputs[0];
    if (!channels?.length) return true;

    for (let index = 0; index < channels[0].length; index += 1) {
      let sample = 0;
      for (const channel of channels) sample += channel[index];
      sample /= channels.length;

      // Use integer time units so fractional sample boundaries never drift.
      let inputRemaining = TARGET_RATE;
      while (inputRemaining > 0) {
        const weight = Math.min(inputRemaining, this.remaining);
        this.weightedSum += sample * weight;
        this.remaining -= weight;
        inputRemaining -= weight;
        if (this.remaining > 0) continue;

        const value = Math.max(-1, Math.min(1, this.weightedSum / sampleRate));
        this.view.setInt16(this.length * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
        this.length += 1;
        this.remaining = sampleRate;
        this.weightedSum = 0;

        if (this.length === FRAME_SAMPLES) {
          this.sendFrame(this.frame);
          this.frame = new ArrayBuffer(FRAME_SAMPLES * 2);
          this.view = new DataView(this.frame);
          this.length = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
