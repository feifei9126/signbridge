// This client has no dictionary, model weights or motion generation fallback.
export function privateEndpoint(value) {
  const url = new URL(value);
  if (
    url.protocol !== "http:" ||
    url.hostname !== "127.0.0.1" ||
    !url.port ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  )
    throw new Error("privateEndpointInvalid");
  return url.origin + "/v1/understand";
}

export async function understand({
  endpoint,
  token,
  text,
  signal,
  fetchImpl = fetch,
}) {
  const url = privateEndpoint(endpoint);
  if (!/^[A-Za-z0-9_-]{40,128}$/.test(token))
    throw new Error("privateTokenInvalid");
  if (typeof text !== "string" || !text.trim() || [...text].length > 500)
    throw new Error("privateTextInvalid");
  const response = await fetchImpl(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + token,
    },
    body: JSON.stringify({ text }),
    credentials: "omit",
    cache: "no-store",
    redirect: "error",
    signal,
  });
  if (!response.ok) {
    const keys = {
      401: "privateUnauthorized",
      403: "privateForbidden",
      429: "privateRateLimited",
      503: "privateBusy",
    };
    throw new Error(keys[response.status] || "privateRequestFailed");
  }
  const result = await response.json();
  if (
    !["parsed", "abstained"].includes(result.status) ||
    !result.roles ||
    typeof result.roles !== "object" ||
    Array.isArray(result.roles) ||
    Object.keys(result.roles).length > 11 ||
    !Object.values(result.roles).every(
      (v) => typeof v === "string" && [...v].length <= 500,
    ) ||
    result.csl_translation_trained !== false
  )
    throw new Error("privateResponseInvalid");
  return result;
}

export function localServicePage(value) {
  return privateEndpoint(value).replace(
    "/v1/understand",
    "/private/index.html",
  );
}

export function needsLocalServicePage(value, pageOrigin, workbench = false) {
  const service = new URL(localServicePage(value));
  if (pageOrigin.startsWith("chrome-extension://")) return workbench;
  return service.origin !== pageOrigin;
}
