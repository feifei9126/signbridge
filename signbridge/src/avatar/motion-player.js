function easeInOut(amount) {
  return amount < 0.5 ? 2 * amount * amount : -1 + (4 - 2 * amount) * amount;
}

function normalizeMotionFrames(input) {
  const frames = Array.isArray(input) ? input : input?.frames;
  if (!Array.isArray(frames) || frames.length === 0) return [];
  return frames.map((frame) => ({
    value: frame?.value && typeof frame.value === "object" ? frame.value : {},
    duration:
      Number.isFinite(frame?.duration) && frame.duration > 0
        ? frame.duration
        : 0.8,
  }));
}

function createMotionPlayer(
  rig,
  {
    requestFrame = requestAnimationFrame,
    cancelFrame = cancelAnimationFrame,
    setTimer = setTimeout,
    clearTimer = clearTimeout,
    now = () => performance.now(),
  } = {},
) {
  let queue = [];
  let timerId = null;
  let frameId = null;
  let playing = false;

  function stop({ reset = false } = {}) {
    playing = false;
    queue = [];
    if (timerId !== null) clearTimer(timerId);
    if (frameId !== null) cancelFrame(frameId);
    timerId = null;
    frameId = null;
    if (reset) rig.reset();
  }

  function playNext() {
    if (!playing || queue.length === 0) {
      playing = false;
      frameId = null;
      timerId = null;
      return;
    }

    const frame = queue.shift();
    const durationMs = frame.duration * 1000;
    const blendMs = Math.max(1, Math.min(durationMs * 0.35, 150));
    const from = rig.capture();
    const targets = rig.createTargets(frame.value);
    const startedAt = now();

    function blend() {
      const elapsed = now() - startedAt;
      const amount = Math.min(elapsed / blendMs, 1);
      rig.interpolate(from, targets, easeInOut(amount));
      if (amount < 1 && playing) frameId = requestFrame(blend);
      else frameId = null;
    }

    blend();
    timerId = setTimer(playNext, durationMs);
  }

  function play(motion) {
    const frames = normalizeMotionFrames(motion);
    if (frames.length === 0) return false;
    stop();
    queue = frames;
    playing = true;
    playNext();
    return true;
  }

  return {
    play,
    stop,
    get isPlaying() {
      return playing;
    },
  };
}

export { createMotionPlayer, easeInOut, normalizeMotionFrames };
