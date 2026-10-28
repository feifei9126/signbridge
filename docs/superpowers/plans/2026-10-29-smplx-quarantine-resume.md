# SMPL-X missing-detection quarantine and queue resume

**Goal:** Resume the authorized 2,112-candidate reconstruction without rerunning existing outputs or accepting incomplete motion as complete.

**Approved scope:** The user approved the preceding next-stage proposal. This increment implements its first step: isolate genuine missing detections and resume remaining chunks. It does not approve new semantics, train models, change checkpoints, or integrate candidates into Demo.

**Design:** Keep strict validation by default. An explicit missing-detection policy permits only exact, report-accounted missing parameter/metadata frame pairs, with complete input/render sets and matching logs and internal hashes. Record complete and quarantined sequences separately. Preserve original reports, output attempts, and the old queue. Use a new, hash-bound queue tool/state directory and an output-root lock to prevent duplicate dispatch.

## Tasks

- [x] Add regression tests: default strict mode, genuine gap classification, mismatched reports, bad hashes, missing renders/metadata, extra person tracks, safe resume, disk reserve, and duplicate dispatch.
- [x] Implement explicit quarantine accounting, per-sequence evidence records, immutable policy/tool provenance and output-root locking in `signbridge/src/tools/sign-smplx-chunk-queue.py`.
- [x] Verify local chunk-001 and chunk-002 with the updated validator; the expected classification is 47 complete candidates and one incomplete candidate with missing frames 48/49.
- [x] Run full build, lint, JavaScript/Python tests and formatting; document and commit the change locally without a GitHub push.
- [x] Recheck remote processes, all frozen input/tool/model/runtime hashes and disk; stage the new queue version separately, preserve old outputs, and launch exactly one queue from the first unprocessed chunk.
- [x] Verify real runner/inference activity and fresh output growth; save timestamped evidence and a desktop status report. Full 88-chunk completion remains ongoing work.

## Non-negotiable data boundaries

Missing detections remain missing. No zero filling, interpolation or features from incomplete candidates. Text is unverified; all new human/training readiness flags remain false. Technical corruption, unexpected tracks, nonzero runner exit, provenance changes or low disk still stop the queue. Failed attempts are never overwritten or automatically retried.

## Verified execution

- The legacy `fits/runtime/` snapshot directory was identified during full real-data validation and covered by a separate regression test; its original hashes remain mandatory.
- Final full verification: 289 JavaScript tests; 638 Python tests, 12 skipped; build, lint and formatting all exit successfully. The queue suite contains 13 tests with additional adverse-case subtests.
- Reverified all 88 input packages, 2,112 sequence tasks / 265,686 frames, three public assets, nine body assets, 307 code/config hashes, both interpreter/dependency inventories and frozen SMPLer-X revision.
- Actual V2 queue launched at 2026-10-29 06:35:54 +08:00, PID 45500, from source commit `e46f960feabdcbd5ce11693934549b5296d93ddb`; tool SHA256 `73965f3852e81d6431a1017784774ecdf8aca21571ba46b72734eb1eed3d5fcb`.
- Snapshot at 06:37:08 +08:00 shows one queue, one runner and one inference child, chunk-003 active, and new native/meta/render files. Existing results account for 48 candidates: 47 complete and one quarantined. The old queue/tool hashes remain unchanged.
- Evidence is in `local-data/word-motion-expansion-20261028-v1/queue-recovery-20261029-v2/` with a separately sealed desktop delivery. This completes the recovery increment, not the entire reconstruction or subsequent motion/semantic quality review.
