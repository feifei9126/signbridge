# Motion Library v2

The public-motion demo now derives one runtime index from the frozen motion inputs:

- 14 T08 reference clips;
- 3 T08 candidate clips;
- 83 approved-for-demo fitted clips;
- 100 total motion entries.

`demo/motion-library-v2.json` is generated during the `public-motion-demo` build. It preserves the source type, original asset path, motion-only review status, and the fact that semantic verification and model-training readiness are still absent.

## Stability audit

The build performs a non-destructive audit over the native 55-joint axis-angle poses. It checks finite values, exact frame counts, adjacent shortest-arc rotation, angular speed, and isolated temporal residuals. The audit produces `stable`, `needs_review`, or `reject` without changing source poses.

The result is a display policy, not a semantic approval:

- `stable` uses `quaternion-temporal-v1` display stabilization;
- `needs_review` uses the stronger `quaternion-temporal-recovery-v1` display policy;
- `reject` remains unavailable to the runtime until the source is repaired.

Five of the ten `needs_review` fitted clips use narrowly tuned, evidence-backed
display profiles from the offline window sweep. The other five retain the
existing recovery profile because no tested window met the fixed wrist/range/
finger screening gates. This is a runtime display choice only; it does not
rewrite source poses or create a new human approval.

Smoothing is display-only. It does not fill missing frames, overwrite native fits, or convert motion-quality approval into Chinese Sign Language semantic approval.

## Build

Use the public motion profile to include the frozen motion assets:

```bash
npm run build:motion
```

The ordinary `npm run build` remains the dictionary-only public build when no research assets are selected.
