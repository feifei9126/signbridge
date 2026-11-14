# Demo Phrase Catalog

The 2026-10-27 public-motion demo exposes **153 deduplicated entries** with the frozen local assets installed. These include words as well as phrases, not 153 trained sentences:

- 14 T08 reference-motion reconstructions from the frozen checkpoint.
- 3 candidate reconstructions encoded with that same checkpoint. They are not training data; source orientation and signer grouping remain unconfirmed.
- 83 approved-for-demo SMPL-X fitted motions. They remain motion-quality evidence only; Chinese meaning, boundaries, mirroring, signer identity and CSL grammar are not certified.
- 53 phrases composed from the built-in dictionary. The demo plays these word motions one at a time. They are not sentence-level model outputs or sign-expert-validated translations.

All 53 composed entries are checked against the current dictionary planner and must have complete text coverage. In addition, a bounded demo semantic route can organize supported templates such as `我帮你`, `你帮我`, `我去`, `你去`, `他去`, `我们去`, `我不去` and `你今天去`. This route preserves participant roles and selects existing dictionary units; it is explicitly an unverified demo approximation, not a trained CSL grammar model.

The runtime motion index is `demo/motion-library-v2.json` and contains exactly 100 source-preserving entries: 14 T08 references, 3 candidates and 83 fitted motions. Each entry records finite-frame checks, a non-destructive stability classification and a display stabilization profile. `stable` and `needs_review` affect display processing only; a `reject` entry would remain unavailable. No source pose is overwritten and missing frames are never filled.

No model weights were updated for this catalog. To add genuinely trained sentence motions, first obtain continuous authorized samples with verified sentence text and boundaries, confirmed mirror orientation, signer/source grouping, hand-quality review, and held-out evaluation. Train into a separate checkpoint and promote it only after comparing both the new phrases and the existing T08 references.

The experimental assets have a separate schema and source badge. They retain motion-only approval, `training_ready=false`, `model_training_ready=false`, `mirror_status=unknown`, and `signer_id=unconfirmed`. The user's relaxed Demo tolerance allows playback, not promotion of training labels. Native hand means are added once; root, lower body and spine remain at rest to match the existing avatar retargeter. No missing-frame interpolation or zero-filled detections are exported. Larger rotation jumps remain labeled and receive the recovery display profile.

The lightweight `experimental-index.json` loads on startup. Individual pose JSON files load only when selected, with SHA-256 verification and bounded caches. Both the standalone Demo and the extension subtitle iframe share this contract. Existing T08 assets and checkpoint hashes are unchanged. Catalog text deduplication prefers T08 references, then old candidates, then experimental fits, then dictionary compositions. Exact subtitle matching retains the existing dictionary fallback on missing or invalid resources.

See [the motion-library build notes](motion-library-v2.md) for the reproducible build command. Assets, rendered evidence, and delivery archives remain local-only unless a separate publication is explicitly authorized.
