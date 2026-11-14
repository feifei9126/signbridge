import { validateAsrEndpoint } from "./asr-config.js";

function audioFileName(type = "") {
  if (type.includes("wav")) return "signbridge-audio.wav";
  if (type.includes("ogg")) return "signbridge-audio.ogg";
  if (type.includes("mp4")) return "signbridge-audio.m4a";
  return "signbridge-audio.webm";
}

function transcriptionError(code, detail = "") {
  const error = new Error(detail || code);
  error.code = code;
  return error;
}

async function transcribeAudio(
  audioBlob,
  requestConfig,
  fetchImpl = globalThis.fetch,
  { signal } = {},
) {
  if (!(audioBlob instanceof Blob) || audioBlob.size === 0) {
    throw transcriptionError("asr-empty-audio");
  }
  if (!fetchImpl) throw transcriptionError("asr-fetch-unavailable");

  const endpoint = validateAsrEndpoint(requestConfig.endpoint);
  const form = new globalThis.FormData();
  form.append("file", audioBlob, audioFileName(audioBlob.type));
  form.append("model", requestConfig.model);
  form.append("response_format", "json");
  if (requestConfig.language && requestConfig.language !== "auto") {
    form.append("language", requestConfig.language);
  }

  const headers = {};
  if (requestConfig.apiKey) {
    headers.Authorization = `Bearer ${requestConfig.apiKey}`;
  }

  let response;
  try {
    response = await fetchImpl(endpoint, {
      method: "POST",
      headers,
      body: form,
      signal,
      credentials: "omit",
      redirect: "error",
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw transcriptionError("asr-network-error", error?.message);
  }

  const body = await response.text();
  let payload = null;
  try {
    payload = body ? JSON.parse(body) : {};
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload?.error?.message || payload?.detail || body;
    throw transcriptionError(`asr-http-${response.status}`, detail);
  }

  const text = String(payload?.text || payload?.result?.text || "").trim();
  return { text, payload };
}

export { transcribeAudio };
