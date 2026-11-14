// One input generation owns both the result and its motion. Stale inference never wins.
export function createModelSession({
  predict,
  onResult,
  onStop,
  onError = () => {},
}) {
  let generation = 0;
  let controller;
  function clear() {
    generation++;
    controller?.abort();
    onStop();
  }
  async function analyze(text) {
    clear();
    const mine = generation;
    controller = new globalThis.AbortController();
    try {
      const result = await predict(text, controller.signal);
      if (mine === generation) onResult(result);
    } catch (error) {
      if (mine === generation && error.name !== "AbortError") onError(error);
    }
  }
  return { analyze, clear };
}
