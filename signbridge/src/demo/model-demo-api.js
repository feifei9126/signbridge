// Browser pages use the same-origin API; extension pages opt into loopback only.
export const MODEL_PROTOCOL = "signbridge-model-demo-v1";
export const MODEL_CHECKPOINT =
  "c6997e70392afac6748999e2e311131e7c2d0928b06da6ee97b184ef13e8af2d";
export const DEFAULT_MODEL_ENDPOINT = "http://127.0.0.1:8787";
const LOOPBACK_PERMISSION = { origins: ["http://127.0.0.1/*"] };
const fail = (code) => Object.assign(new Error(code), { code });
export function normalizeModelEndpoint(value) {
  const match = /^http:\/\/127\.0\.0\.1:([1-9][0-9]{0,4})\/?$/.exec(value);
  if (!match || Number(match[1]) > 65535) throw fail("invalidEndpoint");
  return `http://127.0.0.1:${Number(match[1])}`;
}
function validateSession(info, index) {
  if (
    info?.protocol !== MODEL_PROTOCOL ||
    info.checkpoint_sha256 !== MODEL_CHECKPOINT ||
    typeof info.token !== "string" ||
    !/^[A-Za-z0-9_-]{32,128}$/.test(info.token) ||
    info.research_only !== true ||
    [
      "human_approved",
      "semantics_approved",
      "training_ready",
      "model_training_ready",
      "csl_translation_verified",
    ].some((key) => info[key] !== false) ||
    !Array.isArray(info.catalog) ||
    !info.catalog.length ||
    info.catalog.length > 8
  )
    throw fail("incompatible");
  const seen = new Set();
  for (const item of info.catalog) {
    const local = index.clips?.find((clip) => clip.id === item.id);
    if (
      !local ||
      seen.has(item.id) ||
      item.sha256 !== local.sha256 ||
      item.text !== local.text ||
      item.source !== "experimental" ||
      item.human_approved !== true ||
      local.human_approved !== true ||
      item.approval_scope !== "motion_quality_only" ||
      item.semantic_status !== "unverified" ||
      item.approval_id !== local.motion_approval_id ||
      item.source_sha256 !== local.source_sha256 ||
      item.fitted_sha256 !== local.fitted_sha256
    )
      throw fail("incompatible");
    seen.add(item.id);
  }
  return info;
}
export function createModelApi({
  extension = globalThis.location?.protocol === "chrome-extension:",
  permissions = globalThis.chrome?.permissions,
  fetcher = globalThis.fetch.bind(globalThis),
  loadIndex,
  timeoutMs = 15000,
} = {}) {
  let token = null,
    endpoint = "",
    revision = 0;
  const pending = new Set();
  function disconnect() {
    revision++;
    token = null;
    for (const controller of pending) controller.abort();
    pending.clear();
  }
  async function bounded(work, signal) {
    const controller = new globalThis.AbortController();
    let timedOut = false;
    const abort = () => controller.abort();
    const timer = setTimeout(() => {
      timedOut = true;
      abort();
    }, timeoutMs);
    pending.add(controller);
    let rejectAbort;
    const aborted = new Promise((_, reject) => {
      rejectAbort = reject;
    });
    const onAbort = () =>
      rejectAbort(
        timedOut
          ? fail("serviceError")
          : Object.assign(new Error("Aborted"), { name: "AbortError" }),
      );
    controller.signal.addEventListener("abort", onAbort, { once: true });
    if (signal?.aborted) abort();
    signal?.addEventListener("abort", abort, { once: true });
    try {
      return await Promise.race([
        Promise.resolve().then(() => work(controller.signal)),
        aborted,
      ]);
    } finally {
      clearTimeout(timer);
      pending.delete(controller);
      signal?.removeEventListener("abort", abort);
      controller.signal.removeEventListener("abort", onAbort);
    }
  }
  async function request(path, options = {}, base = endpoint) {
    return bounded(async (signal) => {
      const response = await fetcher(base + path, {
        ...options,
        signal,
        credentials: "omit",
        cache: "no-store",
        redirect: "error",
      });
      if (!response.ok) throw fail("serviceError");
      return response.json();
    }, options.signal);
  }
  return {
    extension,
    get connected() {
      return token !== null;
    },
    disconnect,
    async connect(
      value = DEFAULT_MODEL_ENDPOINT,
      { requestPermission = false } = {},
    ) {
      disconnect();
      const generation = revision;
      endpoint = extension ? normalizeModelEndpoint(value) : "";
      // permissions.request must be invoked synchronously within the click gesture.
      const granted = extension
        ? await (requestPermission
            ? permissions.request(LOOPBACK_PERMISSION)
            : permissions.contains(LOOPBACK_PERMISSION))
        : true;
      if (!granted)
        throw fail(
          requestPermission ? "permissionDenied" : "permissionRequired",
        );
      if (generation !== revision) throw fail("cancelled");
      let info, index;
      try {
        [info, index] = await Promise.all([
          request("/v1/demo-session"),
          loadIndex
            ? bounded(loadIndex)
            : request("experimental-index.json", {}, ""),
        ]);
      } catch (error) {
        if (generation !== revision) throw fail("cancelled");
        throw error;
      }
      if (generation !== revision) throw fail("cancelled");
      validateSession(info, index);
      token = info.token;
      // The bearer token never leaves this transport or enters persisted state.
      const publicInfo = { ...info };
      delete publicInfo.token;
      return publicInfo;
    },
    async predict(text, signal) {
      if (!token) throw fail("disconnected");
      const generation = revision;
      const result = await request("/v1/understand", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ text }),
        signal,
      });
      if (generation !== revision) throw fail("cancelled");
      if (result.checkpoint_sha256 !== MODEL_CHECKPOINT)
        throw fail("incompatible");
      return result;
    },
  };
}
