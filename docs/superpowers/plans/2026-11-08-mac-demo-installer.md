# Mac Demo Installer Implementation Plan

> **For agentic workers:** execute this approved scope inline; user has requested autonomous completion without intermediate confirmations.

**Goal:** Deliver a self-contained Apple-silicon Mac demo installer with no dependency on project or external Python directories.

**Architecture:** Reuse the sealed model Demo assets and Python API. Add a relocatable dependency-closed runtime and a small native launcher that owns its child server and opens the existing UI.

**Tech Stack:** CPython 3.10, frozen PyTorch/Transformers dependencies, Swift/AppKit, pkgbuild, codesign.

## Global Constraints

- Apple-silicon Mac only; minimum advertised macOS 13, tested on actual host.
- No GPU, training, model edits, approval expansion, security-setting changes or GitHub push.
- Native UI text comes from existing locale registry. Chrome installation remains explicit.
- New versioned output in Desktop/手语; preserve previous deliveries.

## Task 1: Parent-owned service and isolated runtime

Files: `src/tools/sign-native-model-serve.py`, `src/tools/sign-mac-demo-bundle.py`, `tests/sign-native-model-serve.test.py`.

- [x] Test port collision fallback and parent identity checks using existing HTTP server fixtures.
- [x] Wrap the verified server, write per-launch state outside app resources, stop when parent is gone.
- [x] Copy standalone Python and the actual installed Torch/Transformers dependency closure; reject missing or mismatched files and remove external .pth hooks.
- [x] Verify `python -I -B` reports only bundled import paths and runs the real checkpoint under a fresh HOME/CWD.

## Task 2: Native launcher and application

Files: `src/tools/mac-demo-launcher.swift`, `src/i18n/locales.js`, bundler above.

- [x] Export native labels from `modelDemo.native*` locale keys.
- [x] Compile arm64 launcher with window status, open-demo/open-plugin/quit controls; auto-open on service readiness.
- [x] Validate state PID, loopback URL and checkpoint before opening; capture only non-secret logs in Application Support.
- [x] Verify move, launch, model and full fitted playback; normal and forced parent termination must close owned service.

## Task 3: Installable artifact and evidence

Files: `docs/mac-demo-installer-20261108.md`, generated desktop artifacts.

- [x] Sign copied app ad-hoc, verify signatures and external dependency audit.
- [x] Build PKG from the exact app; extract package payload and compare files.
- [x] Run app from extracted/copied payload; verify automatic startup and real browser playback.
- [x] Run repository verification, review changes, commit locally; checksum installer and deliver paths with platform/signature limitations.
