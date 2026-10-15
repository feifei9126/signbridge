# Demo Phrase Catalog

The 2026-10-15 demo exposes **153 deduplicated entries** with the local assets installed. These include words as well as phrases, not 153 trained sentences:

- 14 T08 reference-motion reconstructions from the frozen checkpoint.
- 3 candidate reconstructions encoded with that same checkpoint. They are not training data; source orientation and signer grouping remain unconfirmed.
- 83 experimental SMPL-X reconstructions from source 4 (24,900 original, complete frames). The 91 complete source sequences are reduced by eight repeated text/feature entries; the two incomplete sequences never enter this export. Alternate recordings remain in the original evidence, not deleted. For repeated text the export chooses the lower maximum adjacent rotation jump, then a stable ID tie-breaker. This is an automated presentation choice, not motion-quality approval.
- 53 phrases composed from the built-in dictionary. The demo plays these word motions one at a time. They are not sentence-level model outputs or sign-expert-validated translations.

All 53 composed entries are checked against the current dictionary planner and must have complete text coverage. This proves only that the demo can play a sequence of available entries; it does not prove Chinese Sign Language grammar or semantic accuracy.

No model weights were updated for this catalog. To add genuinely trained sentence motions, first obtain continuous authorized samples with verified sentence text and boundaries, confirmed mirror orientation, signer/source grouping, hand-quality review, and held-out evaluation. Train into a separate checkpoint and promote it only after comparing both the new phrases and the existing T08 references.

The experimental assets have a separate schema and source badge. They retain `human_approved=false`, `training_ready=false`, `model_training_ready=false`, `mirror_status=unknown`, and `signer_id=unconfirmed`. The user's relaxed Demo tolerance allows playback, not promotion of training labels. Native hand means are added once; root, lower body and spine remain at rest to match the existing avatar retargeter. No missing-frame interpolation or zero-filled detections are exported. Larger rotation jumps remain labeled.

The lightweight `experimental-index.json` loads on startup. Individual pose JSON files load only when selected, with SHA-256 verification and bounded caches. Both the standalone Demo and the extension subtitle iframe share this contract. Existing T08 assets and checkpoint hashes are unchanged. Catalog text deduplication prefers T08 references, then old candidates, then experimental fits, then dictionary compositions. Exact subtitle matching retains the existing dictionary fallback on missing or invalid resources.

See [the runnable Demo guide](../../docs/demo.md) for startup and reproducible export commands. Assets, rendered evidence, and delivery archives are local-only under `local-data/demo-experimental-20261015/`; none are committed to Git.
