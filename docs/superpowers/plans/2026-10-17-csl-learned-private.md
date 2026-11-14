# CSL learned semantics and private client implementation plan

Goal: train and evaluate bounded Chinese roles and expose them through a thin, asset-free private Demo client.
Architecture: NumPy character sequence tagger; hashed local artifacts; Python loopback inference; isolated MV3 package.

- [x] Add failing model tests for learned role swaps, disjoint splits, explicit synthetic provenance, unknown/complex abstention and safe artifact integrity.
- [x] Implement corpus generation, training, evaluation, safe inference and six-batch readiness inventory in src/tools; train a new ignored local run and preserve all metrics/failures.
- [x] Add failing service/client/package tests for auth, origins, Host, size/rate/concurrency limits, path isolation and absence of private assets.
- [x] Implement local inference service and localized thin client with a separate private build profile. No dictionary playback fallback.
- [x] Restore the motion recovery source as the local build default and verify recovery asset hashes.
- [x] Verify focus tutorial evidence hashes and retain its unresolved human labels.
- [x] Build, lint, format, run Python/JS and browser verification; document limitations, package hashes, reproducible run instructions and commit only scoped changes.

Validation: 205 JS tests, 464 Python tests, build/lint/Prettier, web and unpacked-extension model inference. Delivered learned-roles-v3 and private-client-v2 under ignored local-data. This scoped milestone is complete; actual CSL generation and repository visibility changes are not claimed complete.
