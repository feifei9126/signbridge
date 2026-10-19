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
  if (result.event_graph !== undefined) {
    const graphRoles = eventGraphRoles(result.event_graph);
    if (
      !graphRoles ||
      JSON.stringify(sortedRecord(graphRoles)) !==
        JSON.stringify(sortedRecord(result.roles))
    )
      throw new Error("privateResponseInvalid");
  }
  if (result.expression_plan !== undefined) {
    const plan = result.expression_plan;
    if (
      !plan ||
      plan.can_play !== false ||
      !Array.isArray(plan.motion_items) ||
      plan.motion_items.length ||
      !Array.isArray(plan.components) ||
      plan.components.length > 11 ||
      !plan.components.every(
        (c) =>
          c &&
          typeof c.text === "string" &&
          c.text.length <= 500 &&
          typeof c.role === "string" &&
          result.roles[c.role] === c.text &&
          Array.isArray(c.evidence) &&
          c.evidence.length <= 8 &&
          c.evidence.every(
            (item) =>
              item &&
              typeof item.id === "string" &&
              item.id.length > 0 &&
              item.id.length <= 128 &&
              item.human_approved === false &&
              item.word_boundaries_verified === false &&
              item.training_ready === false,
          ),
      ) ||
      new Set(plan.components.map((c) => c.role)).size !==
        plan.components.length ||
      Object.keys(result.roles).length !== plan.components.length ||
      !Array.isArray(plan.uncovered) ||
      plan.uncovered.length > 11 ||
      !plan.uncovered.every((v) => typeof v === "string" && v.length <= 500) ||
      JSON.stringify([...plan.uncovered].sort()) !==
        JSON.stringify(
          plan.components
            .filter((c) => c.evidence.length === 0)
            .map((c) => c.text)
            .sort(),
        )
    )
      throw new Error("privateResponseInvalid");
  }
  return result;
}

export function localServicePage(value, scopeExperiment = false) {
  const target = privateEndpoint(value).replace(
    "/v1/understand",
    "/private/index.html",
  );
  return scopeExperiment ? `${target}?scope=1` : target;
}

export function needsLocalServicePage(
  value,
  pageOrigin,
  workbench = false,
  scopeExperiment = false,
) {
  const service = new URL(localServicePage(value));
  if (pageOrigin.startsWith("chrome-extension://"))
    return workbench || scopeExperiment;
  return service.origin !== pageOrigin;
}

function validEventGraph(node, depth = 0) {
  if (!node || typeof node !== "object" || Array.isArray(node) || depth > 3)
    return false;
  if (node.type === "event")
    return (
      Object.keys(node).length === 2 &&
      node.roles &&
      typeof node.roles === "object" &&
      !Array.isArray(node.roles) &&
      Object.keys(node.roles).length <= 11 &&
      Object.values(node.roles).every(
        (v) => typeof v === "string" && v.length <= 500,
      )
    );
  return (
    node.type === "operator" &&
    Object.keys(node).length === 3 &&
    /^(negation|modal):[^:]{1,10}$/u.test(node.operator) &&
    validEventGraph(node.argument, depth + 1)
  );
}

function eventGraphRoles(node, roles = {}) {
  if (!validEventGraph(node)) return null;
  if (node.type === "event") return { ...roles, ...node.roles };
  const separator = node.operator.indexOf(":");
  const role = node.operator.slice(0, separator);
  const text = node.operator.slice(separator + 1);
  if (roles[role] !== undefined) return null;
  return eventGraphRoles(node.argument, { ...roles, [role]: text });
}

function sortedRecord(value) {
  return Object.fromEntries(
    Object.entries(value).sort(([a], [b]) => a.localeCompare(b)),
  );
}
