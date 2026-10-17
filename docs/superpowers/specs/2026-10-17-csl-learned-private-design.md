# Learned semantics and private delivery milestone

User confirmed the direction on 2026-10-17. Target remains Chinese text/subtitles to Chinese Sign Language. This iteration trains a real bounded Chinese semantic sequence tagger and serves it privately. It does not rename tokenizer reconstruction or synthetic Chinese parsing as CSL fluency.

## Decision and evaluation

The learned action is semantic role extraction: actor, predicate, patient, goal, time, negation, modality, question, aspect and politeness. Train an averaged structured perceptron with character context features and learned BIO transitions using existing NumPy. Assistant-generated Chinese examples are explicitly synthetic; keep text-disjoint validation/test sets and a separately authored challenge set with unsupported constructions. Report exact frame match, per-slot accuracy, minimal-pair distinctions, abstention and latency, including errors. No candidate motion data or human approval enters these weights. Unsupported or unknown input must abstain; a valid parse does not imply a valid CSL realization.

Keep sentence semantics separate from motion availability. Do not fall back to dictionary playback in the new private interface. At this milestone all newly parsed motions require CSL word alignment/nonmanual/spatial review; the service returns this gap honestly. Existing local motion review remains available separately.

## Private delivery

Create a separate thin MV3 client with localized Chinese text input and semantic output. Its package contains no proprietary lexicon, generated training corpus, model weights, native/experimental motion assets, original videos or animation editor. A local-only Python service loads a hash-verified safe NPZ model from ignored local-data. Require a random per-session bearer token in memory, exact origin allowlisting, loopback Host validation, size and rate limits, bounded concurrency, no CORS wildcard, no static file browsing, no text/token logging. Serve only explicitly named UI resources; never serve model or dataset directories. Do not expose it to the internet without a separate HTTPS/account deployment. No embedded credentials or public publication.

The token is entered by the authorized user into the client and held in session memory. CLI prints the ephemeral token to the local terminal only, never a report or file. Responses include only requested semantic spans and model identity, no downloadable label table or weights. Render using textContent, not HTML. Browser-visible outputs can still be copied. Previously distributed packages/source remain extractable and cannot be recalled by this change.

## Data and existing behavior

Generate a six-batch semantic-readiness inventory from the existing audit, with report hashes and exact incomplete exclusions; all unconfirmed language/word spans/signers remain unconfirmed. Verify tutorial evidence asset hashes before presenting it as usable evidence. No GPU work, model checkpoint mutation, source smoothing, new approvals, external upload or corpus promotion.

Restore display-fix-v2 as the local default experimental source when present, with explicit environment override preserved; source-free builds still work. Produce both the working local legacy review build and a new separately inspectable private-client package. No git push or replacement of old public ZIP.
