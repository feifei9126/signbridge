# Demo Phrase Catalog

The demo exposes 70 phrase entries when its current motion assets load:

- 14 T08 reference-motion reconstructions from the frozen checkpoint.
- 3 candidate reconstructions encoded with that same checkpoint. They are not training data; source orientation and signer grouping remain unconfirmed.
- 53 phrases composed from the built-in dictionary. The demo plays these word motions one at a time. They are not sentence-level model outputs or sign-expert-validated translations.

All 53 composed entries are checked against the current dictionary planner and must have complete text coverage. This proves only that the demo can play a sequence of available entries; it does not prove Chinese Sign Language grammar or semantic accuracy.

No model weights were updated for this catalog. To add genuinely trained sentence motions, first obtain continuous authorized samples with verified sentence text and boundaries, confirmed mirror orientation, signer/source grouping, hand-quality review, and held-out evaluation. Train into a separate checkpoint and promote it only after comparing both the new phrases and the existing T08 references.
