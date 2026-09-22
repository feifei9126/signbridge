import { t } from "../i18n/locales.js";
import {
  MAX_MOTION_BYTES,
  createMotionAsset,
  parseMotionAsset,
  convertLegacyMotion,
  motionIdentity,
} from "./motion-asset.js";
import { createMotionLibrary } from "./motion-library.js";
import { mountMotionPack } from "./motion-pack-ui.js";

function mountMotionLibrary({
  container,
  rig,
  getFrames,
  load,
  preview,
  output,
}) {
  const library = createMotionLibrary(rig);
  let currentId = newId();
  let entries = [];
  let previewed = "";
  let disposed = false;
  let refreshVersion = 0;

  function newId() {
    return `custom_${globalThis.crypto.randomUUID()}`;
  }
  function element(tag, key, parent = container) {
    const node = document.createElement(tag);
    if (key) node.textContent = t(key);
    parent.appendChild(node);
    return node;
  }
  container.replaceChildren();
  element("h3", "motionLibraryTitle");
  element("p", "motionLibraryHelp");
  function field(id, key) {
    const label = element("label", key);
    label.htmlFor = id;
    label.style.display = "block";
    const input = element("input");
    input.id = id;
    input.maxLength = 400;
    input.style.width = "95%";
    return input;
  }
  const name = field("motion-name", "motionName");
  const texts = field("motion-texts", "motionTexts");
  const tags = field("motion-tags", "motionTags");
  const actions = element("div");
  actions.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;margin:8px 0";
  const select = element("select");
  select.id = "motion-list";
  select.setAttribute("aria-label", t("motionLibraryTitle"));
  select.style.width = "100%";
  const status = element("p");
  status.id = "motion-status";
  status.setAttribute("role", "status");

  const requestedText = new URL(globalThis.location.href).hash.slice(1);
  const suggestedText = new globalThis.URLSearchParams(requestedText).get(
    "motion-text",
  );
  if (
    suggestedText?.trim() &&
    suggestedText.length <= 100 &&
    !/[,，\n\r]/.test(suggestedText)
  ) {
    name.value = suggestedText.trim();
    texts.value = suggestedText.trim();
    status.textContent = t("coveragePrefilled");
  }

  function report(error) {
    status.textContent = t("motionFailure", {
      detail: t(error.message, { detail: error.detail || "" }),
    });
    console.warn("[SB-MOTION]", error.message, error.detail || "");
  }
  function action(id, key, handler) {
    const button = element("button", key, actions);
    button.id = id;
    button.type = "button";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await handler();
      } catch (error) {
        report(error);
      } finally {
        button.disabled = false;
      }
    });
    return button;
  }
  const listTexts = (value) =>
    value
      .split(/[,，\n]/)
      .map((text) => text.trim())
      .filter(Boolean);
  function capture() {
    return createMotionAsset(rig, getFrames(), {
      id: currentId,
      gloss: name.value,
      texts: listTexts(texts.value),
      tags: listTexts(tags.value),
    });
  }
  function show(asset) {
    load(asset);
    currentId = asset.id;
    name.value = asset.gloss;
    texts.value = asset.texts.join(", ");
    tags.value = asset.tags.join(", ");
    previewed = "";
    output(JSON.stringify(asset, null, 2));
    status.textContent = t("motionLoaded");
  }
  async function refresh() {
    const version = ++refreshVersion;
    const result = await library.list();
    if (disposed || version !== refreshVersion) return;
    entries = result.entries;
    const selected = select.value;
    select.replaceChildren();
    const empty = element("option", "motionChoose", select);
    empty.value = "";
    for (const entry of entries) {
      const option = element("option", null, select);
      option.value = entry.asset.id;
      option.textContent = `${entry.asset.gloss} · ${t(entry.enabled ? "motionEnabled" : "motionDraft")}`;
    }
    select.value = entries.some((entry) => entry.asset.id === selected)
      ? selected
      : "";
    container.dataset.invalidCount = String(result.invalidCount);
    if (result.invalidCount)
      status.textContent = t("motionIgnored", { count: result.invalidCount });
  }
  action("motion-new", "motionNew", () => {
    currentId = newId();
    name.value = "";
    texts.value = "";
    tags.value = "";
    select.value = "";
    previewed = "";
    status.textContent = t("motionNewHelp");
  });
  async function save() {
    const asset = capture();
    await library.saveDraft(asset);
    previewed = "";
    await refresh();
    select.value = asset.id;
    status.textContent = t("motionSaved");
    return asset;
  }
  action("motion-save", "motionSave", save);
  action("motion-load", "motionLoad", () => {
    const entry = entries.find((item) => item.asset.id === select.value);
    if (!entry) throw new Error("motionSelectFirst");
    show(entry.asset);
  });
  action("motion-preview", "motionPreview", () => {
    const asset = capture();
    preview(asset);
    previewed = motionIdentity(asset);
    status.textContent = t("motionPreviewHelp");
  });
  action("motion-enable", "motionEnable", async () => {
    const asset = capture();
    if (previewed !== motionIdentity(asset))
      throw new Error("motionPreviewFirst");
    if (!confirm(t("motionConfirm"))) return;
    await library.setEnabled(asset.id, true, asset);
    await refresh();
    status.textContent = t("motionEnabledHelp");
  });
  action("motion-disable", "motionDisable", async () => {
    if (!select.value) throw new Error("motionSelectFirst");
    await library.setEnabled(select.value, false);
    await refresh();
    status.textContent = t("motionDisabledHelp");
  });
  action("motion-refresh", "motionRefresh", refresh);

  function exportJson(download = false) {
    const asset = capture();
    const json = JSON.stringify(asset, null, 2);
    output(json);
    if (download) {
      const url = URL.createObjectURL(
        new Blob([json], { type: "application/json" }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${asset.id}.motion.json`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    }
    return asset;
  }
  action("motion-export", "motionExport", () => exportJson(true));
  const format = element("select");
  format.id = "motion-import-format";
  format.setAttribute("aria-label", t("motionImportFormat"));
  for (const [value, key] of [
    ["motion", "motionFormat"],
    ["editor-degrees", "motionLegacyEditor"],
    ["recorder-degrees", "motionLegacyRecorder"],
    ["absolute-radians", "motionLegacyAbsolute"],
  ]) {
    const option = element("option", key, format);
    option.value = value;
  }
  const file = element("input");
  file.id = "motion-import-file";
  file.type = "file";
  file.accept = ".json,application/json";
  file.setAttribute("aria-label", t("motionImport"));
  file.addEventListener("change", async () => {
    try {
      const selected = file.files?.[0];
      if (!selected) return;
      if (selected.size > MAX_MOTION_BYTES)
        throw new Error("motionFileTooLarge");
      const json = await selected.text();
      let asset;
      if (format.value === "motion") asset = parseMotionAsset(json, rig);
      else {
        if (!confirm(t("motionLegacyConfirm"))) return;
        const input = JSON.parse(json);
        asset = convertLegacyMotion(input, format.value, rig, {
          id: newId(),
          gloss: name.value || selected.name,
          texts: listTexts(texts.value),
          tags: listTexts(tags.value),
        });
      }
      show({ ...asset, id: newId() });
    } catch (error) {
      report(error);
    } finally {
      file.value = "";
    }
  });
  action("motion-legacy", "motionMigrate", async () => {
    if (!confirm(t("motionLegacyConfirm"))) return;
    const raw = localStorage.getItem("sb_gestures") || "{}";
    if (new Blob([raw]).size > MAX_MOTION_BYTES)
      throw new Error("motionFileTooLarge");
    const old = JSON.parse(raw);
    const values = Object.entries(old);
    if (values.length > 200) throw new Error("motionFileTooLarge");
    const assets = values.map(([gloss, entry]) =>
      convertLegacyMotion(entry.delta, "editor-degrees", rig, {
        id: newId(),
        gloss,
        texts: [gloss],
        tags: [entry.library || "default"],
      }),
    );
    for (const asset of assets) await library.saveDraft(asset);
    await refresh();
    status.textContent = t("motionMigrated", { count: assets.length });
  });
  const unsubscribe = library.subscribe(() => refresh().catch(report));
  const disposePack = mountMotionPack({ container, rig, library });
  refresh().catch(report);
  return {
    capture,
    exportJson,
    save,
    report,
    importFile: () => file.click(),
    dispose: () => {
      disposed = true;
      unsubscribe();
      disposePack();
    },
  };
}

export { mountMotionLibrary };
