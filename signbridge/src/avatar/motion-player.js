function easeInOut(amount) {
  return amount < 0.5 ? 2 * amount * amount : -1 + (4 - 2 * amount) * amount;
}

function normalizeMotionFrames(input) {
  if (input?.type === "quaternion-track") {
    if (
      !Array.isArray(input.samples) ||
      input.samples.length < 2 ||
      !Number.isFinite(input.fps) ||
      input.fps <= 0 ||
      !Number.isFinite(input.duration) ||
      input.duration <= 0
    )
      return [];
    return [
      {
        track: input.samples,
        fps: input.fps,
        duration: input.duration,
      },
    ];
  }
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
    maxPendingMotions = 2,
    maxPendingAgeMs = 6000,
    onComplete = () => {},
  } = {},
) {
  let queue = [];
  let timerId = null;
  let frameId = null;
  let playing = false;
  let pendingMotions = [];
  let currentKey = null;

  function stop({ reset = false } = {}) {
    playing = false;
    queue = [];
    pendingMotions = [];
    currentKey = null;
    if (timerId !== null) clearTimer(timerId);
    if (frameId !== null) cancelFrame(frameId);
    timerId = null;
    frameId = null;
    if (reset) rig.reset();
  }

  function playNext() {
    if (frameId !== null) cancelFrame(frameId);
    frameId = null;
    timerId = null;
    if (playing && queue.length === 0) {
      pendingMotions = pendingMotions.filter(
        (motion) => now() - motion.receivedAt <= maxPendingAgeMs,
      );
      const next = pendingMotions.shift();
      queue = next?.frames || [];
      currentKey = next?.key ?? null;
    }
    if (!playing || queue.length === 0) {
      playing = false;
      onComplete();
      return;
    }

    const frame = queue.shift();
    if (frame.track) {
      const startedAt = now();
      function animateTrack() {
        if (!playing) return;
        const elapsed = Math.max(0, now() - startedAt) / 1000;
        const framePosition = Math.min(
          elapsed * frame.fps,
          frame.track.length - 1,
        );
        const fromIndex = Math.floor(framePosition);
        const toIndex = Math.min(fromIndex + 1, frame.track.length - 1);
        rig.interpolate(
          frame.track[fromIndex],
          frame.track[toIndex],
          framePosition - fromIndex,
        );
        if (elapsed >= frame.duration) {
          frameId = null;
          playNext();
        } else {
          frameId = requestFrame(animateTrack);
        }
      }
      animateTrack();
      return;
    }
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

  function enqueue(motion, { key = null } = {}) {
    const frames = normalizeMotionFrames(motion);
    if (frames.length === 0) return false;
    if (
      key !== null &&
      (key === currentKey || pendingMotions.some((item) => item.key === key))
    ) {
      return false;
    }
    if (!playing) {
      queue = frames;
      currentKey = key;
      playing = true;
      playNext();
    } else {
      pendingMotions = pendingMotions.filter(
        (item) => now() - item.receivedAt <= maxPendingAgeMs,
      );
      pendingMotions.push({ frames, key, receivedAt: now() });
      while (pendingMotions.length > maxPendingMotions) pendingMotions.shift();
    }
    return true;
  }

  return {
    play,
    enqueue,
    stop,
    get isPlaying() {
      return playing;
    },
  };
}

export { createMotionPlayer, easeInOut, normalizeMotionFrames };
