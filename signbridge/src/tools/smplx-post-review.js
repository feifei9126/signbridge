/* Classic script: works directly under file:// with adjacent review-data.js.
 * The builder exports only postFit LOCALES keys. No network or module loader.
 */
(() => {
  "use strict";
  const PAGE_SIZE = 24;
  const text = (value) =>
    typeof value === "string"
      ? value
      : typeof value === "number" && Number.isFinite(value)
        ? String(value)
        : "";

  function safeMediaPath(value, kind) {
    const name = {
      contact: "contact.jpg",
      original: "original.mp4",
      comparison: "comparison.mp4",
    }[kind];
    if (!name || typeof value !== "string") return "";
    // An allowlist, not URL normalization: no schemes, escapes, query strings,
    // traversal, backslashes or arbitrary filenames can become media sources.
    const match = /^media\/([A-Za-z0-9_-]{1,100})\/([a-z0-9.]+)$/.exec(value);
    return match && match[2] === name ? value : "";
  }

  function mountPostFitReview(data, locales) {
    const records = Array.isArray(data?.records) ? data.records : [];
    const get = (id) => document.querySelector(`#post-fit-${id}`);
    const node = (tag, value, className) => {
      const element = document.createElement(tag);
      if (value !== undefined) element.textContent = value;
      if (className) element.className = className;
      return element;
    };
    const requested =
      new URL(location.href).searchParams.get("lang") || "zh-CN";
    const state = {
      page: 0,
      language: requested.startsWith("zh")
        ? "zh-CN"
        : requested.startsWith("ja")
          ? "ja"
          : "en",
    };
    const t = (key, values = {}) => {
      const value =
        locales?.[state.language]?.[key] || locales?.en?.[key] || key;
      return value.replace(/\{(\w+)\}/g, (_, name) => text(values[name]));
    };
    const display = (value) => text(value) || t("postFitUnknown");
    get("language").value = state.language;

    function releaseVideos() {
      for (const video of get("records").querySelectorAll("video")) {
        video.pause();
        video.removeAttribute("src");
        video.load();
      }
    }

    function field(list, key, value) {
      list.append(node("dt", t(key)), node("dd", display(value)));
    }

    function metrics(value) {
      if (!value || typeof value !== "object") return display(value);
      return (
        Object.entries(value)
          .map(([key, item]) => `${key}: ${metrics(item)}`)
          .join("\n") || t("postFitUnknown")
      );
    }

    function addMedia(card, row) {
      card.append(node("p", t("postFitMediaLegend"), "muted"));
      const sheet = safeMediaPath(row.media?.contact?.path, "contact");
      if (sheet) {
        const image = node("img");
        image.src = sheet;
        image.loading = "lazy";
        image.decoding = "async";
        image.alt = t("postFitContactAlt", {
          label: display(row.label_candidate),
        });
        image.addEventListener("error", () => {
          image.hidden = true;
          status.textContent = t("postFitMediaError");
        });
        const link = node("a", t("postFitOpenContact"));
        link.href = sheet;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        const status = node("p", "", "media-error");
        card.append(image, link, status);
      } else card.append(node("p", t("postFitMediaUnavailable"), "muted"));
      for (const [kind, key] of [
        ["original", "postFitShowOriginal"],
        ["comparison", "postFitShowComparison"],
      ]) {
        const path = safeMediaPath(row.media?.[kind]?.path, kind);
        if (!path) continue;
        const container = node("div", undefined, "video-slot");
        const button = node("button", t(key));
        button.type = "button";
        button.dataset.media = kind;
        button.setAttribute("aria-expanded", "false");
        const slot = node("div");
        let video = null;
        button.addEventListener("click", () => {
          if (video) {
            video.pause();
            video.removeAttribute("src");
            video.load();
            video = null;
            slot.replaceChildren();
            button.textContent = t(key);
          } else {
            video = node("video");
            video.controls = true;
            video.preload = "none";
            video.playsInline = true;
            video.setAttribute("aria-label", t(key));
            video.src = path;
            const error = node("p", "", "media-error");
            video.addEventListener("error", () => {
              error.textContent = t("postFitMediaError");
            });
            slot.append(video, error);
            button.textContent = t("postFitHideMedia");
          }
          button.setAttribute("aria-expanded", String(Boolean(video)));
        });
        container.append(button, slot);
        card.append(container);
      }
    }

    function card(value) {
      const row = value && typeof value === "object" ? value : {};
      const element = node("article", undefined, "candidate-card");
      element.append(
        node("h3", display(row.label_candidate)),
        node("p", display(row.uid), "candidate-id"),
        node("p", t("postFitCandidateOnly"), "candidate-warning"),
        node("p", t("postFitUnassessedQuality"), "muted"),
        node(
          "p",
          t(
            row.review_status === "quarantined_candidate" ||
              row.failures?.length
              ? "postFitQuarantined"
              : "postFitCandidateStatus",
          ),
          "evidence-badge",
        ),
      );
      const quality = node("dl", undefined, "metadata");
      field(quality, "postFitQuality", row.quality_tier);
      field(
        quality,
        "postFitReviewFrames",
        Array.isArray(row.review_frames)
          ? row.review_frames.map(text).join(", ")
          : "",
      );
      field(
        quality,
        "postFitMissingDetections",
        Array.isArray(row.missing_detection_frames)
          ? row.missing_detection_frames.length
            ? row.missing_detection_frames.map(text).join(", ")
            : t("postFitNoneReported")
          : "",
      );
      field(quality, "postFitMetrics", metrics(row.raw_rotation_metrics));
      element.append(quality);
      addMedia(element, row);
      const details = node("details", undefined, "provenance");
      details.append(node("summary", t("postFitProvenance")));
      const list = node("dl", undefined, "metadata");
      for (const [key, value] of [
        ["postFitAnnotation", row.annotation_id],
        ["postFitChunk", row.chunk],
        ["postFitSource", row.source_id],
        ["postFitSourceHash", row.source_sha256],
        ["postFitAuditStatus", row.status],
        ["postFitFps", row.fps],
        ["postFitExpectedFrames", row.frames_expected],
        ["postFitProcessedFrames", row.processed_frames],
        ["postFitClipPath", row.clip_path],
        ["postFitInputDirectory", row.input_directory],
        ["postFitRenderDirectory", row.render_directory],
        ["postFitFitDirectory", row.fit_directory],
        ["postFitTechnicalErrors", metrics(row.technical_errors)],
        ["postFitFailures", metrics(row.failures)],
        [
          "postFitMediaHashes",
          metrics(
            Object.fromEntries(
              ["contact", "original", "comparison"]
                .filter((kind) => row.media?.[kind]?.sha256)
                .map((kind) => [kind, row.media[kind].sha256]),
            ),
          ),
        ],
      ])
        field(list, key, value);
      details.append(list);
      element.append(details);
      return element;
    }

    function render() {
      releaseVideos();
      const search = get("search").value.trim().toLocaleLowerCase();
      const quality = get("quality").value;
      const found = records.filter((value) => {
        const row = value && typeof value === "object" ? value : {};
        return (
          (!quality || text(row.quality_tier) === quality) &&
          (!search ||
            [
              row.uid,
              row.annotation_id,
              row.chunk,
              row.source_id,
              row.label_candidate,
            ].some((value) => text(value).toLocaleLowerCase().includes(search)))
        );
      });
      const pages = Math.max(1, Math.ceil(found.length / PAGE_SIZE));
      state.page = Math.max(0, Math.min(state.page, pages - 1));
      const start = state.page * PAGE_SIZE;
      get("records").replaceChildren(
        ...found.slice(start, start + PAGE_SIZE).map(card),
      );
      get("count").textContent = t("postFitPageCount", {
        start: found.length ? start + 1 : 0,
        end: Math.min(start + PAGE_SIZE, found.length),
        count: found.length,
        page: state.page + 1,
        pages,
      });
      get("previous").disabled = state.page === 0;
      get("next").disabled = state.page + 1 >= pages;
      get("empty").hidden = found.length !== 0;
    }

    function translate() {
      state.language = get("language").value;
      document.documentElement.lang = state.language;
      for (const element of document.querySelectorAll("[data-i18n]"))
        element.textContent = t(element.dataset.i18n);
      const quality = get("quality").value;
      const all = node("option", t("postFitAllQuality"));
      all.value = "";
      get("quality").replaceChildren(all);
      for (const tier of [
        ...new Set(records.map((row) => text(row?.quality_tier))),
      ]
        .filter(Boolean)
        .sort()) {
        const option = node("option", tier);
        option.value = tier;
        get("quality").append(option);
      }
      get("quality").value = quality;
      get("summary").replaceChildren();
      for (const [field, key] of [
        ["total_records", "postFitTotalCandidates"],
        ["successful_media", "postFitSuccessfulMedia"],
        ["failed_candidates", "postFitFailedCandidates"],
        ["failure_count", "postFitFailureCount"],
        ["processed_frames", "postFitProcessedFrames"],
      ]) {
        const cell = node("div");
        cell.append(
          node("dt", t(key)),
          node("dd", display(data?.summary?.[field])),
        );
        get("summary").append(cell);
      }
      get("summary-note").textContent =
        `${t("postFitCandidateOnly")} ${t("postFitUnassessedQuality")}`;
      get("data-status").textContent = Array.isArray(data?.records)
        ? ""
        : t("postFitMissingData");
      render();
    }

    for (const [id, event] of [
      ["search", "input"],
      ["quality", "change"],
    ])
      get(id).addEventListener(event, () => {
        state.page = 0;
        render();
      });
    get("previous").addEventListener("click", () => {
      state.page--;
      render();
    });
    get("next").addEventListener("click", () => {
      state.page++;
      render();
    });
    get("language").addEventListener("change", translate);
    window.addEventListener("pagehide", releaseVideos);
    document.addEventListener("visibilitychange", releaseVideos);
    translate();
    return { releaseVideos };
  }

  globalThis.SignBridgePostFitReview = { mountPostFitReview, safeMediaPath };
  if (typeof document !== "undefined")
    mountPostFitReview(
      globalThis.SIGNBRIDGE_POST_FIT_REVIEW,
      globalThis.SIGNBRIDGE_POST_FIT_LOCALES,
    );
})();
