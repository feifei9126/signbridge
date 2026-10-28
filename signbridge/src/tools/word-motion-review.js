import { setLocale, t } from "../i18n/locales.js";

const PAGE_SIZE = 24;
const SCOPES = [
  ["csl", "CSL_source_scope_unconfirmed", "wordMotionScopeCslUnconfirmed"],
  [
    "regional",
    "regional_variant_candidate_separate",
    "wordMotionScopeRegional",
  ],
  [
    "fingerspelling",
    "fingerspelling_candidate_separate",
    "wordMotionScopeFingerspelling",
  ],
];
const MEDIA_EXTENSIONS = {
  clip: /\.(mp4|webm|ogv|ogg|mov|m4v)$/i,
  sheet: /\.(png|jpe?g|webp|gif|avif)$/i,
  asset: /\.(json|glb|gltf|bvh|fbx|npz|npy|bin|zip)$/i,
};

// Decode once, reject ambiguous encodings and directory escapes, then encode
// every segment ourselves. Never resolve an untrusted scheme or absolute path.
export function safeRelativePath(value, kind) {
  if (typeof value !== "string" || !value || value.trim() !== value)
    return null;
  let decoded;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    return null;
  }
  if (decoded.startsWith("./")) decoded = decoded.slice(2);
  if (
    !decoded ||
    decoded.trim() !== decoded ||
    /[\\:%?#]/.test(decoded) ||
    Array.from(decoded).some(
      (char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127,
    )
  )
    return null;
  const segments = decoded.split("/");
  if (segments.some((part) => !part || part === "." || part === ".."))
    return null;
  if (!MEDIA_EXTENSIONS[kind]?.test(decoded)) return null;
  try {
    return segments.map((part) => encodeURIComponent(part)).join("/");
  } catch {
    // JSON can contain lone UTF-16 surrogates that cannot form a URL.
    return null;
  }
}

const text = (value) =>
  typeof value === "string" || typeof value === "number" ? String(value) : "";
const rows = (value) =>
  Array.isArray(value)
    ? value.filter(
        (row) => row && typeof row === "object" && !Array.isArray(row),
      )
    : [];
const count = (value) =>
  Number.isSafeInteger(value) && value >= 0
    ? String(value)
    : t("wordMotionUnknown");

function scopeLabel(row) {
  const scope = SCOPES.find(
    ([, status]) => status === row.language_scope_status,
  );
  return t(scope?.[2] ?? "wordMotionScopeUnknown");
}

export function mountWordMotionReview(data) {
  const candidates = rows(data?.candidates);
  const coverage = rows(data?.coverage);
  const get = (id) => document.querySelector(`#word-motion-${id}`);
  const node = (tag, value, className) => {
    const element = document.createElement(tag);
    if (value !== undefined) element.textContent = value;
    if (className) element.className = className;
    return element;
  };
  const state = { page: 0, coveragePage: 0, focus: "" };
  const requestedLanguage =
    new URL(location.href).searchParams.get("lang") || "zh-CN";
  const language = requestedLanguage.startsWith("zh")
    ? "zh-CN"
    : requestedLanguage.startsWith("ja")
      ? "ja"
      : "en";
  get("language").value = language;
  const batches = [
    ...new Set([
      ...candidates.map((row) => text(row.source_batch)),
      ...coverage.map((row) => text(row.batch)),
    ]),
  ]
    .filter(Boolean)
    .sort();

  function translate() {
    setLocale(get("language").value);
    document.documentElement.lang = get("language").value;
    for (const element of document.querySelectorAll("[data-i18n]"))
      element.textContent = t(element.dataset.i18n);
    const selectedBatch = get("batch").value;
    const allBatches = node("option", t("wordMotionAllBatches"));
    allBatches.value = "";
    get("batch").replaceChildren(allBatches);
    for (const batch of batches) {
      const option = node("option", batch);
      option.value = batch;
      get("batch").append(option);
    }
    get("batch").value = selectedBatch;
    get("summary").replaceChildren();
    for (const [field, key] of [
      ["videos", "wordMotionVideos"],
      ["unique_sources", "wordMotionUniqueSources"],
      ["candidates", "wordMotionCandidateCount"],
      ["materialized", "wordMotionMaterialized"],
      ["unique_labels", "wordMotionUniqueLabels"],
      ["native_3d", "wordMotionNativeCount"],
    ]) {
      const cell = node("div");
      cell.append(
        node("dt", t(key)),
        node("dd", count(data?.summary?.[field])),
      );
      get("summary").append(cell);
    }
    get("summary-note").textContent = t("wordMotionSummaryNote", {
      count: candidates.length,
    });
    get("data-status").textContent =
      data && Array.isArray(data.candidates) && Array.isArray(data.coverage)
        ? ""
        : t("wordMotionMissingData");
    renderFocus();
  }

  function renderFocus() {
    get("focus").replaceChildren();
    for (const [word, key] of [
      ["", "wordMotionAllWords"],
      ["我", "wordMotionFocusI"],
      ["你", "wordMotionFocusYou"],
      ["他", "wordMotionFocusHe"],
      ["我们", "wordMotionFocusWe"],
    ]) {
      const button = node("button", t(key));
      button.type = "button";
      button.dataset.word = word;
      button.addEventListener("click", () => {
        state.focus = word;
        state.page = 0;
        renderCandidates();
      });
      get("focus").append(button);
    }
  }

  function pauseVideos(release = false) {
    for (const video of get("candidates").querySelectorAll("video")) {
      video.pause();
      if (release) {
        video.removeAttribute("src");
        video.load();
      }
    }
  }

  function pagination(found, pageKey, prefix, messageKey) {
    const pages = Math.max(1, Math.ceil(found.length / PAGE_SIZE));
    state[pageKey] = Math.max(0, Math.min(state[pageKey], pages - 1));
    const start = state[pageKey] * PAGE_SIZE;
    get(`${prefix}count`).textContent = t(messageKey, {
      count: found.length,
      start: found.length ? start + 1 : 0,
      end: Math.min(start + PAGE_SIZE, found.length),
      page: state[pageKey] + 1,
      pages,
    });
    get(`${prefix}previous`).disabled = state[pageKey] === 0;
    get(`${prefix}next`).disabled = state[pageKey] + 1 >= pages;
    return found.slice(start, start + PAGE_SIZE);
  }

  function sourceWindow(row) {
    const seconds = row.source_window_seconds;
    return Array.isArray(seconds) &&
      seconds.length === 2 &&
      seconds.every(
        (value) =>
          typeof value === "number" && Number.isFinite(value) && value >= 0,
      ) &&
      seconds[1] >= seconds[0]
      ? t("wordMotionSeconds", { start: seconds[0], end: seconds[1] })
      : t("wordMotionUnknown");
  }

  function addField(list, key, value, code = false) {
    const detail = node("dd");
    detail.append(
      node(code ? "code" : "span", text(value) || t("wordMotionUnknown")),
    );
    list.append(node("dt", t(key)), detail);
  }

  function addMedia(card, row) {
    const clip = safeRelativePath(row.reference_clip, "clip");
    card.append(node("h4", t("wordMotionClip")));
    if (clip) {
      const video = node("video");
      video.controls = true;
      video.preload = "none";
      video.playsInline = true;
      video.setAttribute(
        "aria-label",
        t("wordMotionClipAlt", { text: text(row.proposed_text) }),
      );
      video.src = clip;
      const error = node("p", "", "media-error");
      error.setAttribute("role", "status");
      video.addEventListener("error", () => {
        error.textContent = t("wordMotionMediaError");
      });
      card.append(video, error);
    } else {
      card.append(
        node("p", t("wordMotionClipUnavailable"), "media-unavailable"),
      );
    }
    const sheet = safeRelativePath(row.keyframes, "sheet");
    if (sheet) {
      const details = node("details", undefined, "contact-sheet");
      const image = node("img");
      image.loading = "lazy";
      image.decoding = "async";
      image.alt = t("wordMotionSheetAlt", { text: text(row.proposed_text) });
      const error = node("p", "", "media-error");
      error.setAttribute("role", "status");
      details.addEventListener("toggle", () => {
        if (details.open && !image.src) image.src = sheet;
      });
      image.addEventListener("error", () => {
        image.hidden = true;
        error.textContent = t("wordMotionMediaError");
      });
      details.append(node("summary", t("wordMotionSheet")), image, error);
      card.append(details);
    } else {
      card.append(node("p", t("wordMotionSheetUnavailable"), "muted"));
    }
    if (row.native_3d_available === true) {
      const asset = safeRelativePath(row.native_asset, "asset");
      if (asset) {
        const link = node("a", t("wordMotionNativeAsset"));
        link.href = asset;
        link.download = "";
        // Chromium may ignore download for opaque file:// origins.
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        card.append(link);
      } else {
        card.append(node("p", t("wordMotionNativeUnavailable"), "muted"));
      }
    }
  }

  function candidateCard(row) {
    const card = node("article", undefined, "candidate-card");
    card.append(
      node("p", t("wordMotionRawLabel"), "eyebrow"),
      node("h3", text(row.proposed_text) || t("wordMotionNoLabel")),
      node("p", t("wordMotionCandidateUnverified"), "candidate-warning"),
      node("p", scopeLabel(row), "scope-badge"),
      node(
        "p",
        t(
          row.native_3d_available === true
            ? "wordMotionNativeReported"
            : "wordMotion2dReported",
        ),
        "evidence-badge",
      ),
      node("p", text(row.id), "candidate-id"),
      node("p", sourceWindow(row), "muted"),
    );
    addMedia(card, row);
    const details = node("details", undefined, "provenance");
    details.append(node("summary", t("wordMotionProvenance")));
    const metadata = node("dl", undefined, "metadata");
    for (const [key, value, code] of [
      ["wordMotionCandidateId", row.id, true],
      ["wordMotionBatch", row.source_batch],
      ["wordMotionSourceId", row.source_id, true],
      ["wordMotionSourceHash", row.source_sha256, true],
      ["wordMotionOriginalPath", row.source_absolute_path, true],
      ["wordMotionWindow", sourceWindow(row)],
      ["wordMotionEvidenceKind", row.evidence_kind],
      ["wordMotionScope", scopeLabel(row)],
      ["wordMotionScopeStatus", row.language_scope_status, true],
      ["wordMotionLabelStatus", row.label_status],
      [
        "wordMotionFlags",
        Array.isArray(row.review_flags)
          ? row.review_flags.map(text).filter(Boolean).join(" · ")
          : "",
      ],
      ["wordMotionNotes", row.notes],
    ])
      addField(metadata, key, value, code);
    details.append(metadata);
    card.append(details);
    return card;
  }

  function renderCandidates() {
    const query = get("search").value.trim().toLowerCase();
    const batch = get("batch").value;
    const kind = get("kind").value;
    const scope = SCOPES.find(([value]) => value === get("scope").value)?.[1];
    const found = candidates.filter((row) => {
      if (scope && row.language_scope_status !== scope) return false;
      if (batch && text(row.source_batch) !== batch) return false;
      if (kind === "native" && row.native_3d_available !== true) return false;
      if (kind === "2d" && row.native_3d_available === true) return false;
      if (state.focus && text(row.proposed_text).trim() !== state.focus)
        return false;
      return (
        !query ||
        [
          row.id,
          row.proposed_text,
          row.source_batch,
          row.source_id,
          row.source_sha256,
          row.source_absolute_path,
          row.evidence_kind,
          row.language_scope_status,
          row.notes,
          ...(Array.isArray(row.review_flags) ? row.review_flags : []),
        ]
          .map(text)
          .join(" ")
          .toLowerCase()
          .includes(query)
      );
    });
    const visible = pagination(found, "page", "", "wordMotionPage");
    pauseVideos(true);
    get("candidates").replaceChildren(...visible.map(candidateCard));
    get("empty").hidden = found.length !== 0;
    for (const button of get("focus").children)
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.word === state.focus),
      );
  }

  function renderCoverage() {
    const batch = get("batch").value;
    const found = coverage.filter((row) => !batch || text(row.batch) === batch);
    const visible = pagination(
      found,
      "coveragePage",
      "coverage-",
      "wordMotionCoveragePage",
    );
    get("coverage-body").replaceChildren();
    for (const row of visible) {
      const tr = node("tr");
      for (const value of [
        row.source_id,
        row.batch,
        row.path,
        row.status,
        count(row.candidate_count),
      ])
        tr.append(node("td", text(value) || t("wordMotionUnknown")));
      get("coverage-body").append(tr);
    }
  }

  get("language").addEventListener("change", () => {
    translate();
    renderCandidates();
    renderCoverage();
  });
  for (const [id, event] of [
    ["search", "input"],
    ["kind", "change"],
    ["batch", "change"],
    ["scope", "change"],
  ])
    get(id).addEventListener(event, () => {
      state.page = 0;
      state.coveragePage = 0;
      renderCandidates();
      renderCoverage();
    });
  for (const [prefix, pageKey, render] of [
    ["", "page", renderCandidates],
    ["coverage-", "coveragePage", renderCoverage],
  ])
    for (const [direction, step] of [
      ["previous", -1],
      ["next", 1],
    ])
      get(`${prefix}${direction}`).addEventListener("click", () => {
        state[pageKey] += step;
        render();
      });
  window.addEventListener("pagehide", () => pauseVideos());
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") pauseVideos();
  });
  translate();
  renderCandidates();
  renderCoverage();
}

if (typeof document !== "undefined")
  mountWordMotionReview(globalThis.SIGNBRIDGE_WORD_MOTIONS);
