import { t } from "../i18n/locales.js";
import { MAX_MOTION_PACK_BYTES, parseMotionPack } from "./motion-pack.js";

function mountMotionPack({ container, rig, library }) {
  let candidate = null;
  let plan = null;
  let generation = 0;
  let disposed = false;
  let importing = false;
  const downloads = new Map();

  function element(tag, key, parent) {
    const node = document.createElement(tag);
    if (key) node.textContent = t(key);
    parent.appendChild(node);
    return node;
  }
  const section = element("details", null, container);
  section.id = "motion-pack";
  element("summary", "motionPackTitle", section);
  element("p", "motionPackHelp", section);
  element("p", "motionPackPrivacy", section);
  function button(id, key) {
    const node = element("button", key, section);
    node.id = id;
    node.type = "button";
    return node;
  }
  const exportButton = button("motion-pack-export", "motionPackExport");
  const label = element("label", "motionPackFile", section);
  label.htmlFor = "motion-pack-file";
  const file = element("input", null, section);
  file.id = "motion-pack-file";
  file.type = "file";
  file.accept = ".json,application/json";
  element("p", "motionPackLimits", section);
  const inspectButton = button("motion-pack-inspect", "motionPackInspect");
  const importButton = button("motion-pack-import", "motionPackImport");
  const clearButton = button("motion-pack-clear", "motionPackClear");
  const status = element("p", null, section);
  status.id = "motion-pack-status";
  status.setAttribute("role", "status");
  const results = element("div", null, section);
  results.id = "motion-pack-results";
  results.hidden = true;

  function controls() {
    inspectButton.disabled = importing || !candidate;
    importButton.disabled =
      importing || !plan || !plan.counts.new || !!plan.counts.conflict;
    clearButton.disabled = importing;
    file.disabled = importing;
    section.setAttribute("aria-busy", String(importing));
  }
  function invalidate(message) {
    generation += 1;
    plan = null;
    results.replaceChildren();
    results.hidden = true;
    status.textContent = message ? t(message) : "";
    controls();
  }
  function report(error) {
    status.textContent = t("motionFailure", {
      detail: t(error.message, { detail: error.detail || "" }),
    });
  }
  function render() {
    results.replaceChildren();
    results.hidden = false;
    const totals = element("p", null, results);
    totals.textContent = t("motionPackSummary", plan.counts);
    const table = element("table", null, results);
    const heading = element("tr", null, element("thead", null, table));
    for (const key of [
      "motionPackName",
      "motionPackState",
      "motionPackWarnings",
    ]) {
      const cell = element("th", key, heading);
      cell.scope = "col";
    }
    const body = element("tbody", null, table);
    const states = {
      new: "motionPackNew",
      existing: "motionPackExisting",
      conflict: "motionPackIdConflict",
    };
    for (const item of plan.items) {
      const row = element("tr", null, body);
      row.dataset.state = item.state;
      const name = element("td", null, row);
      element("span", null, name).textContent = item.gloss;
      element("small", null, name).textContent = item.id;
      element("td", states[item.state], row);
      const warnings = element("td", null, row);
      if (item.wasEnabled) element("p", "motionPackWasEnabled", warnings);
      if (item.aliasConflicts.length)
        element("p", null, warnings).textContent = t("motionPackAliases", {
          aliases: item.aliasConflicts.join(", "),
        });
      if (item.emptyTexts) element("p", "motionPackMaterial", warnings);
    }
    status.textContent = t(
      plan.counts.conflict ? "motionPackConflict" : "motionPackReady",
    );
    controls();
  }
  async function inspect() {
    if (!candidate || disposed || importing) return;
    invalidate("motionPackChecking");
    const version = generation;
    try {
      const result = await library.previewPack(candidate);
      if (disposed || version !== generation) return;
      plan = result;
      render();
    } catch (error) {
      if (!disposed && version === generation) report(error);
    }
  }
  inspectButton.addEventListener("click", inspect);
  file.addEventListener("change", async () => {
    const selected = file.files?.[0];
    candidate = null;
    invalidate();
    const version = generation;
    if (!selected) return;
    try {
      if (selected.size > MAX_MOTION_PACK_BYTES)
        throw new Error("motionPackTooLarge");
      if (!/\.json$/i.test(selected.name)) throw new Error("motionPackInvalid");
      const bytes = await selected.arrayBuffer();
      if (disposed || version !== generation) return;
      let json;
      try {
        json = new globalThis.TextDecoder("utf-8", { fatal: true }).decode(
          bytes,
        );
      } catch {
        throw new Error("motionPackEncoding");
      }
      candidate = parseMotionPack(json, rig);
      file.value = "";
      await inspect();
    } catch (error) {
      if (!disposed && version === generation) report(error);
    } finally {
      if (version === generation) file.value = "";
    }
  });
  clearButton.addEventListener("click", () => {
    candidate = null;
    file.value = "";
    invalidate("motionPackCleared");
  });
  importButton.addEventListener("click", async () => {
    if (!plan || importing || !plan.counts.new || plan.counts.conflict) return;
    const approved = plan;
    if (!confirm(t("motionPackConfirm", { count: approved.counts.new })))
      return;
    importing = true;
    controls();
    try {
      const result = await library.importPack(approved.pack, approved.revision);
      if (disposed) return;
      invalidate();
      status.textContent = t("motionPackImported", result);
    } catch (error) {
      if (!disposed) {
        invalidate();
        report(error);
      }
    } finally {
      importing = false;
      if (!disposed) controls();
    }
  });
  exportButton.addEventListener("click", async () => {
    exportButton.disabled = true;
    try {
      const pack = await library.exportPack();
      if (disposed) return;
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(pack, null, 2)], {
          type: "application/json",
        }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `signbridge-${pack.createdAt.slice(0, 10)}.motion-pack.json`;
      anchor.click();
      downloads.set(
        url,
        setTimeout(() => {
          URL.revokeObjectURL(url);
          downloads.delete(url);
        }, 1000),
      );
      status.textContent = t("motionPackExported", {
        count: pack.motions.length,
      });
    } catch (error) {
      if (!disposed) report(error);
    } finally {
      if (!disposed) exportButton.disabled = false;
    }
  });
  const unsubscribe = library.subscribe(() => {
    if (!disposed && candidate) invalidate("motionPackStale");
  });
  controls();
  return () => {
    disposed = true;
    generation += 1;
    unsubscribe();
    for (const [url, timer] of downloads) {
      clearTimeout(timer);
      URL.revokeObjectURL(url);
    }
    downloads.clear();
    section.remove();
  };
}

export { mountMotionPack };
