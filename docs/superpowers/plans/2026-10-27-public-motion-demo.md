# Public T08 + 83 Motion Demo Implementation Plan

**Goal:** Publish exactly the authorized 14 T08 references, 3 T08 candidates and 83 approved fitted clips as readable versioned assets and a reproducible Chrome Demo ZIP.

**Architecture:** Keep the dictionary-only default and explicit local-research profile unchanged. Add public-motion-demo with a repository-owned, SHA-256-locked allowlist, reusing existing structural, pose and approval validation. No discovery of local-data. Future assets require a new publication decision and manifest.

**Constraints:** No training, checkpoint changes, source videos/images, CE-CSL data or private models. Preserve historical outputs and legacy provenance limitations. All training/deployment readiness remains false. Public distribution does not certify CSL meaning. Existing third-party terms are not relicensed.

## Tasks

- [x] Add failing contracts for public profile isolation, exact release counts/digests and deterministic packaging.
- [x] Extract only authorized JSON from the previously published, hash-verified ZIP into signbridge/assets/public-motion-v1; freeze a manifest and publication notice.
- [x] Implement public-motion-demo build, embedded publication metadata, 1.0.6 version and deterministic packaging command; preserve local-research behavior.
- [x] Run build/lint/JS/Python/format verification plus real browser T08/candidate/83-fit playback; validate archive hashes and every internal file.
- [x] Add versioned downloads and Chinese installation/reproduction/privacy/license documentation. Copy the new verified release to /Users/mac/Desktop/手语 without replacing old packages.
- [ ] Commit only scoped changes; attempt the authorized GitHub publication without force or policy workarounds, then verify remote state or report the actual blocker.

## Verification commands

`cd signbridge && node --test tests/public-motion-assets.test.mjs`

`cd signbridge && python3 tests/sign-public-motion-package.test.py`

`cd signbridge && npm run verify`

`cd signbridge && npm run build:motion && npm run package:motion -- --build dist --output /absolute/new/package.zip`

Browser verification must use the newly extracted ZIP, not an older dist. Distinguish 100 motion clips from independent words or recognized sentences. Never claim generic understanding, recognition or motion-quality certification from playback tests.
