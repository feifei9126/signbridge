# Full SMPL-X transfer, independent audit and quality triage

> For agentic workers: execute the already authorized next round with bounded parallel transfer, audit-tool and media-tool lanes. Preserve source evidence; do not start another fit or training job.

**Goal:** Materialize the complete 2,112-candidate reconstruction locally, independently verify it, and create full-candidate technical/temporal review artifacts.

**Architecture:** Resolve the first ten historical attempt roots explicitly before GNU-tar archiving. Preserve the original interrupted source attempt and both input partitions. A separate transfer tool verifies outer archives, exact member sets, internal hashes and atomic extraction. An independent native auditor handles original and copied-JPEG metadata provenance, then a separate media builder creates offline original/native-render comparisons.

**Tech stack:** Existing OpenSSH master with strict existing host trust, GNU tar on the server, Python stdlib, existing NumPy/OpenCV/Pillow/FFmpeg, project-local Node and locales. No dependency installation, public upload, checkpoint editing, pose filling or model training.

## Frozen contract

- 89 internal partitions, 2,112 ordered fit IDs, 2,132 aliases, 265,686 frames. Server classification: 1,917 structurally complete and 195 missing-detection quarantines; these are not linguistic approvals.
- Server export root: `/root/autodl-tmp/signbridge-exports/post-reconstruction-20261103-v1`.
- Local delivery: `/Users/mac/Desktop/手语/SignBridge-全量重建审计-20261103-v1`.
- Each immutable archive has an outer SHA256 and an exact `.internal.SHA256SUMS` file set. First ten physical historical attempt targets are materialized, not stored as symbolic links.
- Metadata from the reused prefix retains the original `img_path`; longest-prefix origin mappings plus original/copied JPEG hashes must establish provenance. Do not regenerate or rewrite original evidence.
- New data remains `text_verified=''`, `human_approved=false`, `training_ready=false`, `model_training_ready=false`. Do not use incomplete sequences for training features or manufacture labels/mirror/person/split approvals.

## Execution checkpoints

- [x] Recheck terminal status, idle inference, disk and sealed manifest/report anchors; archive all 94 payload groups without changing original outputs.
- [ ] Collect every immutable group, verify outer/internal checksums and exact file sets, extract to fresh paths and record transfer accounting. Code: `signbridge/src/tools/sign-smplx-post-transfer.py`; tests: corresponding `signbridge/tests/sign-smplx-post-transfer.test.py`.
- [ ] Independently audit native shapes/floating dtypes/finite values, exact frames/persons, aliases, metadata origins, all images/video decoding and logs. Code: `signbridge/src/tools/sign-smplx-post-audit.py`; tests: corresponding Python suite. CLI consumes `--results <delivery>/results --export-index <delivery>/export-index.json --output <delivery>/audit-v1 --workers 4`.
- [ ] Calculate raw rotational review diagnostics only for complete sequences. Missing detections remain quarantined; excessive rotation/residuals are risk flags, not proof of semantic or geometric correctness.
- [ ] Create exact-frame original/native-render contact sheets and full comparison videos for every candidate, preserving every failure and non-approval flag. Code: `signbridge/src/tools/sign-smplx-post-review.py`, `smplx-post-review.{html,js,css}`; tests cover path safety, counts, media and pagination. User-visible strings use scoped locale keys in all existing languages.
- [ ] Inspect representative high-risk and missing-detection sheets, publish a full issue/triage report with source hashes, verify media decodability, run full project verification, and commit source/docs locally without pushing GitHub.

## Source and output interfaces

Transfer writes `<delivery>/export-index.json`, `archives/`, immutable `results/`, and `transfer-report.json`; it reports complete only after the remote export index is terminal and every item verifies. Native audit writes `audit-v1/report.json` with summary and `records`: uid, annotation_id, chunk, source identifiers, candidate text, fps/frames, missing detections, errors/status/tier, raw rotational metrics, exact review frames and absolute local clip/input/render/fit paths. Media consumes that report and writes `review-v1/` with self-contained static data, bounded 24-card pagination, per-candidate originals/comparisons/sheets, hashes and failure accounting.

Raw parameters and originals are never overwritten. Display/model quality repair may be proposed from this round's diagnostics, but absent geometry or semantic evidence must remain explicitly unassessed; do not claim all motions are fixed or ready for training.
