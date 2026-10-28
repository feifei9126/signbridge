# Authorized video word-motion expansion

The user authorized expanding the prior proposal to all available videos from the six supplied batches, without repeated approval questions. This execution remains local. CE-CSL stays a separate dataset; its dev/test splits are not mined for new motion labels.

## Deliverables and data contract

1. Rehash original video content and bind captions, source identity, batch and duration. Keep duplicates as aliases and account for every video, including missing or excluded sources.
2. Reuse all 80 prior tutorial word/phrase/fingerspelling references. Add isolated caption/title candidates and explicitly quoted instructional subunits. Long-caption vocabulary is context only: do not divide a sentence duration among text tokens or declare motion alignment.
3. Materialize new candidate clips and three-frame contact sheets with FFmpeg. Reuse old reference clips only after checking their exact hashes, durations and frame counts. Record original time windows as nominal unless actual source PTS are measured. Missing observations stay missing.
4. Reuse complete native 3D clips when exact identity/pose/hash evidence exists. Do not treat five MANO snapshots as continuous animation. Native availability does not certify lexical semantics or cropping boundaries.
5. Generate a paginated local review UI, lexical coverage report (including pronouns), source coverage, failures and internal hashes. Source labels remain candidates; text_verified stays empty, all readiness flags remain false. The frozen public library and existing user approvals are not expanded.
6. Add regression tests for time windows, source hashes, duplicate handling, candidate-vs-context separation and evidence provenance. Run build, lint, formatting and relevant suites. Deliver new local data artifacts and commit tool/UI changes only, without pushing GitHub.

## Implementation surfaces

- Main worker: `signbridge/src/tools/sign-word-motion-library.py`, `signbridge/tests/sign-word-motion-library.test.py`, processing recipe and generated `local-data/word-motion-expansion-20261028-v1/` outputs.
- Parallel source inventory worker: discovery/video-inventory.json and inventory-notes.md only.
- Parallel native evidence worker: discovery/native-motion-map.json and motion-notes.md only.
- Parallel review UI worker: word-motion-review.{html,js,css}, UI tests and wordMotion locale keys only.

## Acceptance boundaries

The stage is complete when every available source is accounted for, all identifiable candidate units are indexed, eligible standalone examples are physically extracted, genuine 3D availability is distinguished from 2D/video-only evidence, artifacts are verified, and coverage gaps are explicit. It does not promise every subtitle word has a correctly aligned CSL action or that a new model has been trained.

## Execution record

- Source inventory/native reuse discovery completed; originals and historical inputs retained.
- Candidate extraction V1 completed with 2 legacy-native compatibility failures preserved. V2 reuses checksum-verified reference clips, adds pinned existing sequence-descriptor/reference-clip validation, and completes 2,132 clips / 16 native projection crops with 0 failures.
- Independent full audit passes 2,132 videos / 267,967 decoded frames, 15,297 package files and 7,157 inputs. Exact native sets and arrays remain unchanged; original JPEG/PTS gaps explicit.
- Offline UI now separates unconfirmed CSL, regional and fingerspelling scopes. Actual corpus browser QA and synthetic security fixtures remain distinct.
- Additional CPU visual sidecar accounts for all 2,132 candidates / 6,396 keyframes, preserves uncertain visibility and all approval gates, and retains black-background/face-detector limitations.
- Final local delivery and source commit follow the last whole-project verification; no GitHub push or model training in this stage.
