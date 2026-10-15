// Evidence-only intake review, with no approval controls or model promotion.
import {
  readFileSync,
  writeFileSync,
  existsSync,
  mkdirSync,
  realpathSync,
  openSync,
  closeSync,
  readSync,
} from "node:fs";
import {
  resolve,
  relative,
  isAbsolute,
  sep,
  join,
  basename,
  dirname,
} from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { parseArgs } from "node:util";
import { t, setLocale } from "../i18n/locales.js";

function digest(path) {
  const stream = openSync(path, "r"),
    hash = createHash("sha256"),
    buffer = Buffer.alloc(1024 * 1024);
  try {
    let count;
    while ((count = readSync(stream, buffer, 0, buffer.length, null)))
      hash.update(buffer.subarray(0, count));
  } finally {
    closeSync(stream);
  }
  return hash.digest("hex");
}
function inside(root, path) {
  if (typeof path !== "string" || isAbsolute(path))
    throw new Error("Unsafe relative artifact path");
  const target = realpathSync(resolve(root, path));
  const rel = relative(realpathSync(root), target);
  if (!rel || rel === ".." || rel.startsWith(".." + sep) || isAbsolute(rel))
    throw new Error("Artifact escaped its root");
  return target;
}
const escape = (text) =>
  String(text ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );

export function buildIntakeReview({
  batch,
  output,
  locale = "zh-CN",
  refinement = null,
}) {
  batch = realpathSync(batch);
  output = resolve(output);
  output = join(realpathSync(dirname(output)), basename(output));
  const rel = relative(batch, output);
  if (existsSync(output) || !rel || rel.startsWith("..") || isAbsolute(rel))
    throw new Error("Choose a new review output inside the batch");
  setLocale(locale);
  const inputs = new Map();
  const artifact = (root, path, expected) => {
    const file = inside(root, path),
      hash = inputs.get(file) || digest(file);
    if (expected && hash !== expected)
      throw new Error("Artifact digest differs: " + path);
    inputs.set(file, hash);
    return file;
  };
  const json = (path) =>
    JSON.parse(readFileSync(artifact(batch, path), "utf8"));
  const jsonl = (path) =>
    readFileSync(artifact(batch, path), "utf8")
      .split(/\r?\n/)
      .filter((line) => line.trim())
      .map((line) => JSON.parse(line));
  const intake = json("intake-v1/sources.json"),
    inventory = json("inventory-v1/inventory.json");
  const screen = json("ocr-screen-v1/screen.json"),
    validation = json("validation.json");
  const candidates = jsonl("candidate-index-v1/caption-candidates.jsonl"),
    shortlist = jsonl("candidate-index-v1/manual-review-shortlist.jsonl");
  if (
    validation.status !== "passed" ||
    screen.status !== "screened_new_sources_pending_candidate_review"
  )
    throw new Error("Intake evidence audit must pass first");
  const sources = new Map(
    intake.sources.map((source) => [source.source_id, source]),
  );
  const original = (source) =>
    artifact(intake.source_root, source.relative_path, source.sha256);
  for (const source of intake.sources) {
    original(source);
    artifact(join(batch, "intake-v1"), source.overview);
  }
  for (const row of candidates) {
    if (
      row.text_verified !== "" ||
      row.human_approved !== false ||
      row.training_ready !== false ||
      row.model_training_ready !== false ||
      row.language !== "unconfirmed" ||
      row.mirror_status !== "unknown" ||
      row.split !== "unassigned"
    )
      throw new Error("Do not manufacture review approvals or metadata");
    if (sources.get(row.source_id)?.sha256 !== row.source_sha256)
      throw new Error("Candidate source provenance differs");
    for (const evidence of row.evidence)
      artifact(
        join(batch, "ocr-screen-v1"),
        evidence.image,
        evidence.image_sha256,
      );
  }
  const revised = refinement ? json(refinement) : null;
  if (
    revised &&
    (revised.schema !== "signbridge-reference-refinement-report-v1" ||
      revised.status !== "audited_pending_human_review" ||
      revised.human_approved !== false ||
      revised.training_ready !== false ||
      revised.model_training_ready !== false ||
      revised.samples !== revised.references?.length ||
      revised.frames !==
        revised.references.reduce((sum, row) => sum + row.frames, 0))
  )
    throw new Error("Refinement must retain audited, unapproved provenance");
  const references = revised ? revised.references : validation.references || [];
  const byReference = new Map();
  for (const row of references) {
    if (
      row.human_approved !== false ||
      row.training_ready !== false ||
      row.model_training_ready !== false ||
      row.text_verified !== "" ||
      sources.get(row.source_id)?.sha256 !== row.source_sha256 ||
      byReference.has(row.annotation_id)
    )
      throw new Error("Invalid or duplicate 2D reference provenance");
    for (const item of Object.values(row.artifacts))
      artifact(batch, item.path, item.sha256);
    if (revised) {
      const prior = row.previous_reference;
      if (
        row.revision_of_annotation_id !== row.annotation_id ||
        row.semantics_approved !== false ||
        row.boundaries_approved !== false ||
        row.language !== "unconfirmed" ||
        row.mirror_status !== "unknown" ||
        row.split !== "unassigned" ||
        prior?.annotation_id !== row.annotation_id ||
        prior.source_sha256 !== row.source_sha256
      )
        throw new Error("Invalid refinement lineage or fabricated approval");
      for (const item of Object.values(prior.artifacts))
        artifact(batch, item.path, item.sha256);
      for (const item of [row.keyframe_sheet, row.visual_evidence].filter(
        Boolean,
      ))
        artifact(batch, item.path, item.sha256);
    }
    byReference.set(row.annotation_id, row);
  }
  const byCandidate = new Map(
    candidates.map((row) => [row.annotation_id, row]),
  );
  const selected = [
    ...new Set([
      ...references.map((row) => row.annotation_id),
      ...(revised ? [] : shortlist.map((row) => row.annotation_id)),
    ]),
  ].map((id) => {
    if (!byCandidate.has(id))
      throw new Error("Review selection is absent from the caption index");
    return byCandidate.get(id);
  });
  const href = (file) => escape(pathToFileURL(file).href);
  const cards = selected
    .map((row) => {
      const source = sources.get(row.source_id),
        ref = byReference.get(row.annotation_id);
      const samples = [
        ...new Set([
          0,
          Math.floor(row.evidence.length / 2),
          row.evidence.length - 1,
        ]),
      ].map((i) => row.evidence[i]);
      const images = samples
        .map(
          (item) =>
            `<figure><img loading="lazy" width="${Number(source.width) || 960}" height="${Number(source.height) || 540}" src="${href(inside(join(batch, "ocr-screen-v1"), item.image))}" alt="${escape(row.label_candidate)}"><figcaption>${Number(item.source_seconds).toFixed(2)}s · OCR ${Math.round(item.confidence * 100)}%</figcaption></figure>`,
        )
        .join("");
      const media = ref
        ? `<p>${escape(t("catchupCoverage", { left: ref.usable_hand_observation_frames.left, right: ref.usable_hand_observation_frames.right, frames: ref.frames }))}</p><p><code>${escape(ref.review_flags.join(" / "))}</code></p><div class="videos"><section><h3>${escape(t("catchupOriginal"))}</h3><video controls preload="none" width="${Number(ref.width)}" height="${Number(ref.height)}" src="${href(inside(batch, ref.artifacts["clip.mp4"].path))}"></video></section><section><h3>${escape(t("catchupOverlay"))}</h3><video controls preload="none" width="${Number(ref.width)}" height="${Number(ref.height)}" src="${href(inside(batch, ref.artifacts["overlay.mp4"].path))}"></video></section></div>`
        : "";
      const proposal = revised
        ? `<p>${escape(t("intakePrevious", { start: ref.previous_reference.start_seconds, end: ref.previous_reference.end_seconds, text: ref.previous_reference.label }))}</p><p>${escape(t("intakeCoverageComparison", { before: ((ref.coverage_before.any_hand_detected_frames / ref.coverage_before.frames) * 100).toFixed(0), after: ((ref.coverage_after.any_hand_detected_frames / ref.coverage_after.frames) * 100).toFixed(0) }))}</p><p>${escape(t("intakeRefinedWindow", { start: ref.start_seconds, end: ref.end_seconds, frames: ref.frames, duration: (ref.frames / ref.fps).toFixed(2) }))}</p><div class="videos"><section><h3>${escape(t("intakeBefore"))}</h3><video controls preload="none" width="${Number(ref.previous_reference.width) || 540}" height="${Number(ref.previous_reference.height) || 960}" src="${href(inside(batch, ref.previous_reference.artifacts["clip.mp4"].path))}"></video></section><section><h3>${escape(t("intakeAfter"))}</h3><video controls preload="none" width="${Number(ref.width)}" height="${Number(ref.height)}" src="${href(inside(batch, ref.artifacts["clip.mp4"].path))}"></video></section></div><details><summary>${escape(t("catchupKeyframes"))}</summary>${[
            ref.keyframe_sheet,
            ref.visual_evidence,
          ]
            .filter(Boolean)
            .map(
              (item) =>
                `<img loading="lazy" src="${href(inside(batch, item.path))}" alt="${escape(ref.label)}">`,
            )
            .join("")}</details>`
        : "";
      const start = revised ? ref.start_seconds : row.start_seconds_nominal,
        end = revised ? ref.end_seconds : row.end_seconds_nominal;
      return `<article id="${escape(row.annotation_id)}"><h2>${escape(revised ? ref.label : row.label_candidate)} <small>${escape(t(revised ? "intakeRefinementPending" : "intakePending"))}</small></h2><p>${escape(t("intakeWindow", { start: row.start_seconds_nominal.toFixed(2), end: row.end_seconds_nominal.toFixed(2), confidence: (row.ocr_confidence_mean * 100).toFixed(0) + "%" }))}</p><p>${escape(source.relative_path)}</p><p><code>${escape(row.annotation_id)} · ${escape(row.source_sha256)}</code></p><a href="${href(original(source))}#t=${start},${end}">${escape(t("intakeOriginal"))}</a>${proposal}<div class="evidence">${images}</div>${revised ? `<details><summary>${escape(t("catchupOverlay"))}</summary>${media}</details>` : media}</article>`;
    })
    .join("");
  const sourceCards = inventory.unique_sources
    .map((row) => {
      const source = sources.get(row.source_id);
      return `<details><summary>${escape(source.relative_path)}${row.duplicate_with_prior_registry ? " · " + escape(t("intakeDuplicate")) : ""}</summary><p><code>${escape(row.content_class)} · ${escape(source.sha256)}</code></p><img loading="lazy" class="overview" width="960" height="640" src="${href(inside(join(batch, "intake-v1"), source.overview))}" alt="${escape(source.relative_path)}"><p><a href="${href(original(source))}">${escape(t("intakeOriginal"))}</a></p></details>`;
    })
    .join("");
  const title = t(revised ? "intakeRefinementTitle" : "intakeTitle", {
    name: basename(intake.source_root),
  });
  const summary = t("intakeSummary", {
    files: intake.sources.length,
    unique: inventory.unique_sources.length,
    screened: screen.sources.length,
    candidates: candidates.length,
    references: references.length,
    frames: references.reduce((sum, row) => sum + row.frames, 0),
  });
  const html = `<!doctype html><html lang="${escape(locale)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escape(title)}</title><style>*{box-sizing:border-box}body{max-width:1200px;margin:auto;padding:24px;background:#fff;color:#173339;font:15px/1.65 system-ui,sans-serif}h1,h2{line-height:1.35}h2{font-size:20px}small{font-size:12px;color:#806125}p,code,summary{overflow-wrap:anywhere}a{color:#176d60}header,article,details{padding:20px 0;border-bottom:1px solid #dbe3df}nav{display:flex;flex-wrap:wrap;gap:20px}.evidence,.videos{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}figure{margin:16px 0}img,video{max-width:100%;height:auto}video{width:100%;background:#e8eeeb}.overview{width:min(100%,640px)}summary{cursor:pointer}figcaption{font-size:12px;color:#64736f}@media(max-width:650px){body{padding:16px}.evidence,.videos{grid-template-columns:1fr}}</style></head><body><header><h1>${escape(title)}</h1><p>${escape(summary)}</p><p>${escape(t("intakeLimits"))}</p><nav><a href="#candidates">${escape(t("catchupCaptions"))}</a><a href="#sources">${escape(t("catchupSources"))}</a><a href="review-data.json">${escape(t("catchupIndex"))}</a></nav></header><main><h2 id="candidates">${escape(t("catchupCaptions"))}</h2>${cards}<h2 id="sources">${escape(t("catchupSources"))}</h2>${sourceCards}</main></body></html>`;
  mkdirSync(output);
  const data = {
    schema: "signbridge-intake-review-v1",
    summary,
    candidates: selected,
    references,
    refinement,
    sources: inventory.unique_sources,
    training_ready: false,
    human_approved: false,
    inputs: [...inputs].map(([path, sha256]) => ({ path, sha256 })),
  };
  writeFileSync(join(output, "index.html"), html);
  writeFileSync(
    join(output, "review-data.json"),
    JSON.stringify(data, null, 2) + "\n",
  );
  writeFileSync(
    join(output, "SHA256SUMS"),
    ["index.html", "review-data.json"]
      .map((name) => `${digest(join(output, name))}  ${name}\n`)
      .join(""),
  );
  return {
    output,
    candidates: selected.length,
    references: references.length,
    sources: intake.sources.length,
  };
}
if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const { values } = parseArgs({
    options: {
      batch: { type: "string" },
      output: { type: "string" },
      locale: { type: "string", default: "zh-CN" },
      refinement: { type: "string" },
    },
  });
  if (!values.batch || !values.output)
    throw new Error("--batch and --output are required");
  console.log(JSON.stringify(buildIntakeReview(values)));
}
