import { t, setLocale } from "../../i18n/locales.js";

setLocale(new URL(location.href).searchParams.get("lang") || "zh-CN");
for (const element of document.querySelectorAll("[data-i18n]"))
  element.textContent = t(element.dataset.i18n);
const data = window.CATCHUP_DATA;
const list = document.querySelector("#list");
let view = "references";
let page = 0;
const sizes = { references: 8, sources: 20, subtitles: 50 };
const node = (tag, text) => {
  const result = document.createElement(tag);
  if (text !== undefined) result.textContent = text;
  return result;
};
const summary = data.summary;
document.querySelector("#summary").textContent = t("catchupSummary", {
  files: summary.source_paths,
  sources: summary.unique_sources,
  windows: summary.reference_windows,
  frames: summary.reference_frames,
  sampled: summary.independent_audit_frames,
});
document.querySelector("#limits").textContent = t("catchupLimits");
function render() {
  const query = document.querySelector("#search").value.trim().toLowerCase();
  const found = data[view].filter((row) =>
    JSON.stringify(row).toLowerCase().includes(query),
  );
  const size = sizes[view];
  page = Math.max(0, Math.min(page, Math.ceil(found.length / size) - 1));
  document.querySelector("#count").textContent = t("catchupPage", {
    count: found.length,
    page: page + 1,
    pages: Math.max(1, Math.ceil(found.length / size)),
  });
  document.querySelector("#previous").disabled = page === 0;
  document.querySelector("#next").disabled = (page + 1) * size >= found.length;
  list.replaceChildren();
  for (const row of found.slice(page * size, (page + 1) * size)) {
    const section = node("section");
    if (view === "references") {
      section.append(node("h2", row.text));
      section.append(
        node(
          "p",
          `${row.id} · ${row.start}–${row.end}s · ${row.frames} frames`,
        ),
      );
      section.append(
        node(
          "p",
          t("catchupCoverage", {
            left: row.leftEligible,
            right: row.rightEligible,
            frames: row.frames,
          }),
        ),
      );
      const pair = node("div");
      pair.className = "pair";
      for (const [name, path] of [
        ["catchupOriginal", row.clip],
        ["catchupOverlay", row.overlay],
      ]) {
        const cell = node("div");
        cell.append(node("h3", t(name)));
        const video = node("video");
        video.controls = true;
        video.preload = "none";
        video.src = path;
        cell.append(video);
        pair.append(cell);
      }
      section.append(pair);
      const button = node("button", t("catchupSync"));
      button.type = "button";
      button.addEventListener("click", async () => {
        const [a, b] = section.querySelectorAll("video");
        if (!a.paused || !b.paused) {
          a.pause();
          b.pause();
          return;
        }
        b.currentTime = a.currentTime;
        const result = await Promise.allSettled([a.play(), b.play()]);
        if (result.some((value) => value.status === "rejected")) {
          a.pause();
          b.pause();
          document.querySelector("#media-status").textContent =
            t("catchupMediaError");
        }
      });
      section.append(button);
      const details = node("details");
      details.append(node("summary", t("catchupKeyframes")));
      const image = node("img");
      image.loading = "lazy";
      image.src = row.sheet;
      image.alt = t("catchupKeyframeAlt", { text: row.text });
      details.append(image);
      section.append(details);
    } else if (view === "sources") {
      section.append(node("h2", row.aliases[0]));
      section.append(node("p", `${row.source_id} · ${row.source_sha256}`));
      section.append(
        node(
          "p",
          t("catchupSourceStages", {
            prior: row.prior_reference_windows,
            motions: row.prior_continuous_motions,
            fresh: row.new_sentence_windows,
            sampled: row.new_independent_observation_frames,
          }),
        ),
      );
      if (row.language_hint === "HKSL_title_hint_unverified")
        section.append(node("p", t("catchupHksl")));
      if (row.sheet) {
        const image = node("img");
        image.loading = "lazy";
        image.src = row.sheet;
        image.alt = t("catchupIndependentAlt");
        section.append(image);
      }
    } else {
      section.append(node("h2", row.text || t("catchupEmptyCaption")));
      section.append(node("p", `${row.sourceId} · ${row.seconds}s`));
    }
    list.append(section);
  }
}
for (const button of document.querySelectorAll("[data-view]"))
  button.addEventListener("click", () => {
    for (const video of list.querySelectorAll("video")) video.pause();
    view = button.dataset.view;
    page = 0;
    for (const item of document.querySelectorAll("[data-view]"))
      item.setAttribute("aria-pressed", String(item === button));
    render();
  });
document.querySelector("#search").addEventListener("input", () => {
  page = 0;
  render();
});
document.querySelector("#previous").addEventListener("click", () => {
  page--;
  render();
});
document.querySelector("#next").addEventListener("click", () => {
  page++;
  render();
});
window.addEventListener("pagehide", () => {
  for (const video of list.querySelectorAll("video")) video.pause();
});
render();
