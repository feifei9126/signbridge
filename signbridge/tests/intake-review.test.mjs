import test from "node:test";
import assert from "node:assert/strict";
import {
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  readFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import * as review from "../src/tools/sign-intake-review.mjs";

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "sign-intake-review-"));
  const batch = join(root, "source-6"),
    output = join(batch, "review");
  const write = (path, value) => {
    mkdirSync(join(batch, path, ".."), { recursive: true });
    writeFileSync(
      join(batch, path),
      typeof value === "string" ? value : JSON.stringify(value),
    );
  };
  const sha = (value) => createHash("sha256").update(value).digest("hex");
  const source = {
    source_id: "source-a",
    relative_path: "video.mp4",
    sha256: sha("video"),
    overview: "overview/source-a.jpg",
    duration_seconds: 10,
  };
  mkdirSync(join(root, "videos"));
  writeFileSync(join(root, "videos/video.mp4"), "video");
  const row = {
    annotation_id: "source-a-cap-0001",
    source_id: "source-a",
    source_sha256: source.sha256,
    label_candidate: "候选<img src=x onerror=alert(1)>",
    start_seconds_nominal: 1,
    end_seconds_nominal: 5,
    ocr_confidence_mean: 0.5,
    evidence: [
      {
        image: "source-a/frame.jpg",
        image_sha256: sha("image"),
        source_seconds: 2,
        confidence: 0.5,
      },
    ],
    text_verified: "",
    human_approved: false,
    training_ready: false,
    model_training_ready: false,
    language: "unconfirmed",
    mirror_status: "unknown",
    split: "unassigned",
  };
  write("intake-v1/sources.json", {
    source_root: join(root, "videos"),
    sources: [source],
  });
  write("intake-v1/overview/source-a.jpg", "overview");
  write("inventory-v1/inventory.json", {
    unique_sources: [
      {
        ...source,
        content_class: "tutorial_content_unconfirmed",
        duplicate_with_prior_registry: false,
      },
    ],
  });
  write("ocr-screen-v1/source-a/frame.jpg", "image");
  write("ocr-screen-v1/screen.json", {
    status: "screened_new_sources_pending_candidate_review",
    sources: [{ source_id: "source-a", screening_images: 1 }],
  });
  write(
    "candidate-index-v1/caption-candidates.jsonl",
    JSON.stringify(row) + "\n",
  );
  write(
    "candidate-index-v1/manual-review-shortlist.jsonl",
    JSON.stringify(row) + "\n",
  );
  write("validation.json", { status: "passed", references: [] });
  return { root, batch, output, row, write };
}
test("intake review renders unverified evidence safely without changing labels", () => {
  const f = fixture();
  try {
    review.buildIntakeReview(f);
    const html = readFileSync(join(f.output, "index.html"), "utf8");
    assert.ok(html.includes("&lt;img"));
    assert.ok(!html.includes("<img src=x onerror"));
    assert.ok(html.includes("training_ready=false"));
    const data = JSON.parse(readFileSync(join(f.output, "review-data.json")));
    assert.equal(data.candidates[0].human_approved, false);
    assert.equal(data.candidates[0].text_verified, "");
    assert.equal(data.references.length, 0);
    assert.throws(() => review.buildIntakeReview(f));
  } finally {
    rmSync(f.root, { recursive: true, force: true });
  }
});
test("review rejects approval fabrication and OCR evidence escaping the batch", () => {
  const f = fixture();
  try {
    f.write(
      "candidate-index-v1/caption-candidates.jsonl",
      JSON.stringify({ ...f.row, human_approved: true }),
    );
    assert.throws(() => review.buildIntakeReview(f));
    writeFileSync(join(f.root, "outside.jpg"), "image");
    f.write(
      "candidate-index-v1/caption-candidates.jsonl",
      JSON.stringify({
        ...f.row,
        evidence: [{ ...f.row.evidence[0], image: "../../outside.jpg" }],
      }),
    );
    assert.throws(() => review.buildIntakeReview(f));
  } finally {
    rmSync(f.root, { recursive: true, force: true });
  }
});
test("refined review compares old/new windows without certifying the proposed text", () => {
  const f = fixture();
  try {
    const sha = (value) => createHash("sha256").update(value).digest("hex");
    f.write("old.mp4", "old");
    f.write("new.mp4", "new");
    f.write("overlay.mp4", "overlay");
    const ref = {
      annotation_id: f.row.annotation_id,
      source_id: f.row.source_id,
      source_sha256: f.row.source_sha256,
      label: "建议完整文字",
      text_verified: "",
      start_seconds: 5,
      end_seconds: 9,
      frames: 100,
      fps: 25,
      human_approved: false,
      semantics_approved: false,
      boundaries_approved: false,
      model_training_ready: false,
      training_ready: false,
      language: "unconfirmed",
      mirror_status: "unknown",
      split: "unassigned",
      revision_of_annotation_id: f.row.annotation_id,
      width: 540,
      height: 960,
      usable_hand_observation_frames: { left: 40, right: 80 },
      review_flags: [],
      coverage_before: { frames: 100, any_hand_detected_frames: 10 },
      coverage_after: { frames: 100, any_hand_detected_frames: 80 },
      previous_reference: {
        ...f.row,
        label: f.row.label_candidate,
        start_seconds: 1,
        end_seconds: 5,
        artifacts: { "clip.mp4": { path: "old.mp4", sha256: sha("old") } },
      },
      artifacts: {
        "clip.mp4": { path: "new.mp4", sha256: sha("new") },
        "overlay.mp4": { path: "overlay.mp4", sha256: sha("overlay") },
      },
    };
    const report = {
      schema: "signbridge-reference-refinement-report-v1",
      status: "audited_pending_human_review",
      samples: 1,
      frames: 100,
      human_approved: false,
      training_ready: false,
      model_training_ready: false,
      references: [ref],
    };
    f.write("refinement.json", report);
    review.buildIntakeReview({ ...f, refinement: "refinement.json" });
    const html = readFileSync(join(f.output, "index.html"), "utf8");
    assert.ok(html.includes("建议完整文字"));
    assert.ok(html.includes("old.mp4") && html.includes("new.mp4"));
    assert.ok(html.includes("不同窗口"));
    assert.ok(html.includes("未人工确认"));
    const data = JSON.parse(readFileSync(join(f.output, "review-data.json")));
    assert.equal(data.references[0].text_verified, "");
    assert.equal(data.refinement, "refinement.json");
    f.write("refinement.json", {
      ...report,
      references: [{ ...ref, semantics_approved: true }],
    });
    assert.throws(() =>
      review.buildIntakeReview({
        ...f,
        output: join(f.batch, "rejected-review"),
        refinement: "refinement.json",
      }),
    );
  } finally {
    rmSync(f.root, { recursive: true, force: true });
  }
});
