(() => {
  const status = document.querySelector("#status");
  if (!status) throw new Error("Open the local Live Copilot page first.");

  const label = document.createElement("label");
  label.textContent = "Prerecorded synthetic microphone input ";
  const picker = document.createElement("input");
  picker.type = "file";
  picker.accept = ".wav,audio/wav";
  label.append(picker);
  document.querySelector("main").prepend(label);

  picker.addEventListener("change", () => {
    const [file] = picker.files;
    if (!file) return;
    navigator.mediaDevices.getUserMedia = async () => {
      const context = new AudioContext();
      await context.resume();
      const source = context.createBufferSource();
      source.buffer = await context.decodeAudioData(await file.arrayBuffer());
      const destination = context.createMediaStreamDestination();
      source.connect(destination);

      const observer = new MutationObserver(() => {
        if (status.dataset.state === "live") {
          observer.disconnect();
          source.start();
          source.onended = () => source.disconnect();
        } else if (["completed", "failed"].includes(status.dataset.state)) {
          observer.disconnect();
        }
      });
      observer.observe(status, { attributes: true });
      const cleanup = new MutationObserver(() => {
        if (["completed", "failed"].includes(status.dataset.state)) {
          cleanup.disconnect();
          void context.close();
        }
      });
      cleanup.observe(status, { attributes: true });
      return destination.stream;
    };
  });
})();
