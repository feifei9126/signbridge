# Demo Motion Stability and Bounded Understanding Implementation Plan

> **For agentic workers:** This plan is executed inline in the current local workspace. GitHub push is explicitly out of scope.

**Goal:** Make the local demo use one provenance-aware motion library, suppress display jitter and stale playback, and add a small evidence-bounded Chinese semantic routing layer for demonstrable pronoun and simple-verb sentences.

**Architecture:** Build-time code will derive a single `motion-library-v2.json` from the frozen public motion inputs and calculate non-destructive stability metrics for every T08 reference, T08 candidate, and approved fitted clip. Runtime playback will use latest-input-wins for realtime subtitles, preserve explicit fallback provenance, and apply the same bounded display stabilization policy to all learned motion sources. The demo will expose only supported semantic templates and will never promote semantic drafts to verified CSL or training data.

**Tech Stack:** ES modules, Node `node:test`, Three.js quaternions, existing build profiles and frozen public-motion-v1 assets.

## Global Constraints

- Do not modify source poses, checkpoints, raw videos, or provenance records.
- Do not interpolate missing observations or silently turn failed learned playback into dictionary playback.
- Keep `training_ready`, `model_training_ready`, and `deployment_ready` false.
- Do not push GitHub in this task.
- Preserve T08, candidate, approved-fit, and dictionary source labels separately.
- All user-visible strings must be added through `src/i18n/locales.js`.

### Task 1: Build the unified motion-library index and audit

**Files:**
- Create: `signbridge/src/tools/motion-library-audit.mjs`
- Modify: `signbridge/scripts/build.mjs`
- Modify: `signbridge/scripts/public-motion-assets.mjs`
- Create: `signbridge/tests/motion-library-audit.test.mjs`
- Create: `signbridge/docs/motion-library-v2.md`

**Deliverable:** Build-time `demo/motion-library-v2.json` containing 100 source-preserving entries, finite-motion checks, stability metrics, and `stable|needs_review|reject` classifications. The source JSON assets remain immutable.

### Task 2: Apply stable display processing to all learned motion sources

**Files:**
- Modify: `signbridge/src/demo/demo-retarget.js`
- Modify: `signbridge/src/demo/demo-avatar.js`
- Modify: `signbridge/src/avatar/iframe-bundle.js`
- Modify: `signbridge/tests/demo-retarget.test.mjs`
- Modify: `signbridge/tests/realtime-motion-browser-qa.mjs`

**Deliverable:** T08, candidate, and approved fitted motions use the indexed display policy. The UI still reports the original source and marks display stabilization separately.

### Task 3: Replace realtime queueing with latest-input-wins and safe transitions

**Files:**
- Modify: `signbridge/src/avatar/motion-player.js`
- Modify: `signbridge/src/avatar/iframe-bundle.js`
- Modify: `signbridge/tests/motion-player.test.mjs`
- Modify: `signbridge/tests/realtime-motion-browser-qa.mjs`

**Deliverable:** Realtime subtitles cancel stale loads and pending clips, while manual demo sequences retain ordered playback. New tracks blend from the current rig pose for a bounded transition.

### Task 4: Add bounded semantic routing for the demo

**Files:**
- Modify: `signbridge/src/demo/csl-semantic-plan.js`
- Modify: `signbridge/src/demo/demo-motion.js`
- Modify: `signbridge/src/demo/phrase-catalog.js`
- Modify: `signbridge/src/demo/demo.js`
- Modify: `signbridge/src/i18n/locales.js`
- Modify: `signbridge/tests/csl-semantic-plan.test.mjs`
- Modify: `signbridge/tests/demo-motion.test.mjs`

**Deliverable:** Support a small explicit template set for `我/你/他/我们` with simple verbs, preserve actor/patient direction, and route only when all required motion evidence exists. Unsupported or unverified structures remain analysis-only with visible status.

### Task 5: Full verification and local demo acceptance

**Files:**
- Modify: `signbridge/README.md`
- Modify: `signbridge/docs/demo.md`
- Create: `local-data/demo-motion-optimization-20261027/verification.json`

**Deliverable:** Run build, lint, formatting, JavaScript tests, Python tests, browser QA, and a local public-motion build. Save exact verification counts, source digest, motion-library digest, and the explicit non-training status.
