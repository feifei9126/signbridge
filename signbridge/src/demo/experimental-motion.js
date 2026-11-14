import { MOTION_STABILIZATION_PROFILES } from "./motion-stabilization.js";

// Independent contract for unreviewed, demo-only fitted motions.
const digestPattern = /^[a-f0-9]{64}$/;
export const EXPERIMENTAL_MODEL_SHA256 =
  "376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992";
export function experimentalPreviewSample(clips, currentText, defaultText) {
  return currentText === defaultText &&
    clips.length &&
    clips.every((c) => c.preview_only)
    ? clips[0].text
    : currentText;
}
const previewFields = [
  "source_batch",
  "preview_only",
  "text_verified",
  "semantics_approved",
  "boundaries_approved",
  "temporal_interpolation",
  "source_annotation_id",
  "source_clip_sha256",
  "source_frames_sha256",
  "source_fit_manifest_sha256",
  "boundary_review_flags",
];
function validPreview(c) {
  if (c.source_batch === undefined) return c.preview_only === undefined;
  return (
    c.source_batch === "source-6" &&
    c.preview_only === true &&
    c.text_verified === "" &&
    c.semantics_approved === false &&
    c.boundaries_approved === false &&
    c.temporal_interpolation === false &&
    typeof c.source_annotation_id === "string" &&
    /^[a-zA-Z0-9_-]+$/.test(c.source_annotation_id) &&
    [
      c.source_clip_sha256,
      c.source_frames_sha256,
      c.source_fit_manifest_sha256,
    ].every((v) => digestPattern.test(v)) &&
    Array.isArray(c.boundary_review_flags) &&
    c.boundary_review_flags.every((v) => typeof v === "string")
  );
}
function validMetadata(c, approvalId = undefined) {
  const approved = c?.human_approved === true;
  return (
    typeof c?.id === "string" &&
    /^[a-zA-Z0-9_-]+$/.test(c.id) &&
    typeof c.text === "string" &&
    c.text.trim() &&
    Array.isArray(c.aliases) &&
    c.aliases.length > 0 &&
    c.aliases.every((a) => typeof a === "string" && a.trim()) &&
    Number.isInteger(c.frames) &&
    c.frames >= 4 &&
    c.frames <= 2000 &&
    Number.isFinite(c.fps) &&
    c.fps > 0 &&
    c.fps <= 120 &&
    c.experimental === true &&
    (c.display_stabilization_profile === undefined ||
      Object.hasOwn(
        MOTION_STABILIZATION_PROFILES,
        c.display_stabilization_profile,
      )) &&
    c.model_output === "smplx_fit_demo" &&
    c.training_data_member === false &&
    c.training_ready === false &&
    c.model_training_ready === false &&
    (approved
      ? c.motion_review_status === "approved_for_demo_motion" &&
        typeof approvalId === "string" &&
        c.motion_approval_id === approvalId
      : c.human_approved === false &&
        c.motion_review_status === "needs_review" &&
        c.motion_approval_id === undefined) &&
    c.mirror_status === "unknown" &&
    c.signer_id === "unconfirmed" &&
    validPreview(c) &&
    typeof c.quality_warning === "boolean" &&
    [c.source_sha256, c.feature_sha256, c.fitted_sha256].every((v) =>
      digestPattern.test(v),
    )
  );
}
function validApprovalReference(reference) {
  return (
    reference?.schema === "signbridge-human-motion-approval-ref-v1" &&
    typeof reference.id === "string" &&
    /^[a-zA-Z0-9_-]+$/.test(reference.id) &&
    reference.scope === "motion_quality_only" &&
    reference.asset === "experimental/motion-approval.json" &&
    digestPattern.test(reference.sha256)
  );
}
export function validateExperimentalIndex(data) {
  if (
    data?.schema !== "signbridge-experimental-motion-index-v1" ||
    data.representation !== "effective-smplx-55-axis-angle" ||
    data.smplx_rest_model_sha256 !== EXPERIMENTAL_MODEL_SHA256 ||
    data.training_weights_updated !== false ||
    data.text_to_sign_trained !== false ||
    data.training_ready !== false ||
    data.model_training_ready !== false ||
    data.research_only !== true ||
    !Array.isArray(data.clips) ||
    data.clips.length > 200 ||
    data.restJoints?.length !== 55 ||
    data.parents?.length !== 55 ||
    !data.restJoints.every(
      (v) => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite),
    ) ||
    !data.parents.every(
      (p, i) => Number.isInteger(p) && (i === 0 ? p === -1 : p >= 0 && p < i),
    )
  )
    throw new Error("demoInvalidExperimentalAsset");
  const approval = data.motion_approval;
  if (
    (approval !== undefined && !validApprovalReference(approval)) ||
    (approval === undefined &&
      data.clips.some((clip) => clip.human_approved === true)) ||
    (approval !== undefined &&
      !data.clips.some((clip) => clip.human_approved === true))
  )
    throw new Error("demoInvalidExperimentalAsset");
  const ids = new Set();
  for (const c of data.clips) {
    if (
      !validMetadata(c, approval?.id) ||
      ids.has(c.id) ||
      c.asset !== `experimental/${c.id}.json` ||
      !digestPattern.test(c.sha256)
    )
      throw new Error("demoInvalidExperimentalAsset");
    ids.add(c.id);
  }
  return data;
}
export function validateExperimentalApprovalRecord(index, record) {
  const reference = index.motion_approval;
  const approved = index.clips.filter((clip) => clip.human_approved === true);
  if (
    !reference ||
    record?.schema !== "signbridge-human-motion-approval-v1" ||
    record.id !== reference.id ||
    record.scope !== reference.scope ||
    typeof record.declaration !== "string" ||
    !record.declaration.trim() ||
    record.basis !== "explicit_user_statement_in_current_conversation" ||
    typeof record.captured_at_utc !== "string" ||
    !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(record.captured_at_utc) ||
    !digestPattern.test(record.source_index_sha256) ||
    !Array.isArray(record.clips) ||
    record.clips.length !== approved.length
  )
    throw new Error("demoInvalidExperimentalAsset");
  const items = new Map(record.clips.map((item) => [item.id, item]));
  if (items.size !== approved.length)
    throw new Error("demoInvalidExperimentalAsset");
  for (const entry of approved) {
    const item = items.get(entry.id);
    if (
      !item ||
      !digestPattern.test(item.reviewed_asset_sha256) ||
      item.source_sha256 !== entry.source_sha256 ||
      item.fitted_sha256 !== entry.fitted_sha256 ||
      !digestPattern.test(item.poses_sha256)
    )
      throw new Error("demoInvalidExperimentalAsset");
  }
  return items;
}
export function experimentalPoseDigestInput(poses) {
  return poses
    .flat(2)
    .map((value) => String(Math.floor(value * 1e6 + 0.5)))
    .join(",");
}
export function validateExperimentalClip(data, entry) {
  if (
    data?.schema !== "signbridge-experimental-clip-v1" ||
    !validMetadata(data, entry.motion_approval_id) ||
    ![
      "id",
      "text",
      "frames",
      "fps",
      "source_sha256",
      "feature_sha256",
      "fitted_sha256",
      "quality_warning",
      "display_stabilization_profile",
      "human_approved",
      "motion_review_status",
      "motion_approval_id",
    ].every((key) => data[key] === entry[key]) ||
    JSON.stringify(data.aliases) !== JSON.stringify(entry.aliases) ||
    !previewFields.every(
      (key) => JSON.stringify(data[key]) === JSON.stringify(entry[key]),
    ) ||
    data.poses?.length !== data.frames ||
    !data.poses.every(
      (p) =>
        Array.isArray(p) &&
        p.length === 55 &&
        p.every(
          (v) => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite),
        ),
    )
  )
    throw new Error("demoInvalidExperimentalAsset");
  return data;
}
export function createExperimentalLoader(
  index,
  fetchAsset = (path) => fetch(path),
) {
  validateExperimentalIndex(index);
  const cache = new Map();
  let approvalPromise;
  async function loadApprovalRecord() {
    if (!index.motion_approval) return null;
    if (!approvalPromise) {
      approvalPromise = (async () => {
        const response = await fetchAsset(index.motion_approval.asset);
        if (!response.ok) throw new Error("demoInvalidExperimentalAsset");
        const bytes = await response.arrayBuffer();
        const hash = [
          ...new Uint8Array(
            await globalThis.crypto.subtle.digest("SHA-256", bytes),
          ),
        ]
          .map((v) => v.toString(16).padStart(2, "0"))
          .join("");
        if (hash !== index.motion_approval.sha256)
          throw new Error("demoInvalidExperimentalAsset");
        const record = JSON.parse(new globalThis.TextDecoder().decode(bytes));
        return validateExperimentalApprovalRecord(index, record);
      })();
      approvalPromise.catch(() => {
        approvalPromise = undefined;
      });
    }
    return approvalPromise;
  }
  return {
    async load(id) {
      const entry = index.clips.find((c) => c.id === id);
      if (!entry) throw new Error("demoInvalidExperimentalAsset");
      if (!cache.has(id)) {
        const pending = (async () => {
          const response = await fetchAsset(entry.asset);
          if (!response.ok) throw new Error("demoInvalidExperimentalAsset");
          const bytes = await response.arrayBuffer();
          const hash = [
            ...new Uint8Array(
              await globalThis.crypto.subtle.digest("SHA-256", bytes),
            ),
          ]
            .map((v) => v.toString(16).padStart(2, "0"))
            .join("");
          if (hash !== entry.sha256)
            throw new Error("demoInvalidExperimentalAsset");
          const clip = JSON.parse(new globalThis.TextDecoder().decode(bytes));
          validateExperimentalClip(clip, entry);
          if (entry.human_approved === true) {
            const approvalItems = await loadApprovalRecord();
            const item = approvalItems?.get(entry.id);
            const poseHash = [
              ...new Uint8Array(
                await globalThis.crypto.subtle.digest(
                  "SHA-256",
                  new globalThis.TextEncoder().encode(
                    experimentalPoseDigestInput(clip.poses),
                  ),
                ),
              ),
            ]
              .map((v) => v.toString(16).padStart(2, "0"))
              .join("");
            if (!item || poseHash !== item.poses_sha256)
              throw new Error("demoInvalidExperimentalAsset");
          }
          return clip;
        })();
        cache.set(id, pending);
        // Bound memory when browsing many long clips. Eviction never invalidates active tracks.
        if (cache.size > 6) cache.delete(cache.keys().next().value);
        pending.catch(() => {
          if (cache.get(id) === pending) cache.delete(id);
        });
      }
      return cache.get(id);
    },
    clear() {
      cache.clear();
    },
  };
}
