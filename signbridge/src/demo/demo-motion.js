import { SIGNS } from "../avatar/sign-language-data.js";
export const T08_CHECKPOINT_SHA256 =
  "438cbe537ad1b5bf14c795375209eb00d87cea5c3e97ed06f880f9764e8f9a5b";
const punctuation = /[\s\p{P}]/u;
export function demoTextKey(text) {
  return String(text)
    .normalize("NFKC")
    .replace(/[\s\p{P}]/gu, "")
    .toLocaleLowerCase();
}
export function matchT08Reference(input, clips = []) {
  const key = demoTextKey(input);
  if (!key) return null;
  return (
    clips.find((clip) =>
      [clip.text, ...(clip.aliases || [])].some(
        (text) => demoTextKey(text) === key,
      ),
    ) || null
  );
}
export function planDemoText(input, mode = "auto", clips = []) {
  if (!["auto", "t08", "dictionary"].includes(mode))
    throw new Error("demoInvalidMode");
  const chars = [...String(input).normalize("NFKC")].slice(0, 500);
  const entries = [];
  if (mode !== "dictionary")
    for (const c of clips)
      for (const text of c.aliases || [c.text])
        entries.push({
          id: c.id,
          text,
          key: demoTextKey(text),
          source: c.runtime_candidate ? "candidate" : "t08",
          label: c.text,
        });
  if (mode !== "t08")
    for (const c of Object.values(SIGNS))
      for (const text of c.texts)
        entries.push({
          id: c.id,
          text,
          key: demoTextKey(text),
          source: "dictionary",
          label: c.gloss,
        });
  entries.sort(
    (a, b) =>
      [...b.key].length - [...a.key].length ||
      (a.source === b.source
        ? 0
        : { t08: 0, candidate: 1, dictionary: 2 }[a.source] -
          { t08: 0, candidate: 1, dictionary: 2 }[b.source]),
  );
  const items = [],
    unknown = [];
  let cursor = 0;
  while (cursor < chars.length) {
    if (punctuation.test(chars[cursor])) {
      cursor++;
      continue;
    }
    const remaining = demoTextKey(chars.slice(cursor).join(""));
    const match = entries.find((e) => e.key && remaining.startsWith(e.key));
    if (!match) {
      unknown.push(chars[cursor++]);
      continue;
    }
    let end = cursor,
      consumed = "";
    while (end < chars.length && consumed.length < match.key.length) {
      if (!punctuation.test(chars[end]))
        consumed += chars[end].toLocaleLowerCase();
      end++;
    }
    // English aliases must match a whole token, not prefixes inside unknown words.
    if (
      /^[a-z]+$/i.test(match.key) &&
      (/[a-z0-9]/i.test(chars[end] || "") ||
        /[a-z0-9]/i.test(chars[cursor - 1] || ""))
    ) {
      unknown.push(chars[cursor++]);
      continue;
    }
    items.push({ ...match, matchedText: chars.slice(cursor, end).join("") });
    cursor = end;
    if (items.length >= 40) {
      unknown.push(...chars.slice(cursor));
      break;
    }
  }
  return {
    items,
    unmatched: unknown.join(""),
    truncated: [...String(input)].length > 500,
    matchedCount: items.length,
  };
}
export function validateT08Bundle(data) {
  if (
    data?.schema !== "signbridge-t08-demo-v1" ||
    data.checkpoint_sha256 !== T08_CHECKPOINT_SHA256 ||
    data.research_only !== true ||
    data.text_to_sign_trained !== false ||
    data.representation !== "effective-smplx-55-axis-angle" ||
    data.checkpoint_step !== 1000 ||
    !Array.isArray(data.clips) ||
    data.clips?.length !== 14 ||
    data.parents?.length !== 55 ||
    data.restJoints?.length !== 55
  )
    throw new Error("demoInvalidAsset");
  const ids = new Set();
  for (const c of data.clips) {
    if (
      ids.has(c.id) ||
      typeof c.id !== "string" ||
      typeof c.text !== "string" ||
      !c.text ||
      c.model_output !== "token_decode" ||
      c.text_to_sign_generated !== false ||
      !Number.isFinite(c.token_decode_parity_max) ||
      c.token_decode_parity_max > 1e-4 ||
      !/^[a-f0-9]{64}$/.test(c.feature_sha256) ||
      !/^[a-f0-9]{64}$/.test(c.source_sha256) ||
      !Number.isInteger(c.frames) ||
      !Number.isFinite(c.fps) ||
      c.fps <= 0 ||
      c.poses?.length !== c.frames ||
      c.frames < 4 ||
      c.frames > 2000
    )
      throw new Error("demoInvalidAsset");
    ids.add(c.id);
    if (
      !["body", "left", "right"].every(
        (s) =>
          Array.isArray(c.tokens?.[s]) &&
          c.tokens[s].length === Math.ceil(c.frames / 4) &&
          c.tokens[s].every(
            (n) =>
              Number.isInteger(n) && n >= 0 && n < (s === "body" ? 16 : 32),
          ),
      )
    )
      throw new Error("demoInvalidAsset");
    if (
      !c.poses.every(
        (p) =>
          p.length === 55 &&
          p.every((v) => v.length === 3 && v.every(Number.isFinite)),
      )
    )
      throw new Error("demoInvalidAsset");
  }
  if (
    !data.restJoints.every((p) => p.length === 3 && p.every(Number.isFinite)) ||
    data.parents.some(
      (p, i) => !Number.isInteger(p) || (i === 0 ? p !== -1 : p < 0 || p >= i),
    )
  )
    throw new Error("demoInvalidAsset");
  return data;
}

export function validateT08CandidateBundle(data) {
  if (
    data?.schema !== "signbridge-t08-motion-candidates-v1" ||
    data.training_checkpoint_sha256 !== T08_CHECKPOINT_SHA256 ||
    data.training_weights_updated !== false ||
    data.training_ready !== false ||
    data.text_to_sign_trained !== false ||
    data.research_only !== true ||
    data.training_checkpoint_step !== 1000 ||
    data.representation !== "effective-smplx-55-axis-angle" ||
    data.smplx_rest_model_sha256 !==
      "376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992" ||
    data.clips?.length !== 3 ||
    data.parents?.length !== 55 ||
    data.restJoints?.length !== 55
  )
    throw new Error("demoInvalidCandidateAsset");
  const ids = new Set();
  for (const clip of data.clips) {
    if (
      ids.has(clip.id) ||
      typeof clip.id !== "string" ||
      typeof clip.text !== "string" ||
      !clip.id ||
      !clip.text ||
      !Array.isArray(clip.aliases) ||
      !clip.aliases.every((alias) => typeof alias === "string" && alias) ||
      !/^[a-f0-9]{64}$/.test(clip.feature_sha256) ||
      !/^[a-f0-9]{64}$/.test(clip.source_sha256) ||
      clip.runtime_candidate !== true ||
      clip.training_data_member !== false ||
      clip.training_ready !== false ||
      clip.mirror_orientation_confirmed !== false ||
      clip.speaker_identity_confirmed !== false ||
      clip.authorization_status !== "user_reported" ||
      clip.motion_review_decision_sha256 !==
        "8297549518aaed82f88b94ff20550f4d708ddfe2229a1c614300a7f962752507" ||
      !Number.isFinite(clip.normalized_reconstruction_mse) ||
      clip.normalized_reconstruction_mse < 0 ||
      clip.model_output !== "token_decode_candidate" ||
      !Number.isFinite(clip.token_decode_parity_max) ||
      clip.token_decode_parity_max > 1e-4 ||
      !Number.isInteger(clip.frames) ||
      !Number.isFinite(clip.fps) ||
      clip.fps <= 0 ||
      clip.poses?.length !== clip.frames ||
      clip.frames < 4 ||
      clip.frames > 2000
    )
      throw new Error("demoInvalidCandidateAsset");
    ids.add(clip.id);
    if (
      !["body", "left", "right"].every(
        (part) =>
          Array.isArray(clip.tokens?.[part]) &&
          clip.tokens[part].length === Math.ceil(clip.frames / 4) &&
          clip.tokens[part].every(
            (token) =>
              Number.isInteger(token) &&
              token >= 0 &&
              token < (part === "body" ? 16 : 32),
          ),
      ) ||
      !clip.poses.every(
        (pose) =>
          pose.length === 55 &&
          pose.every(
            (vector) => vector.length === 3 && vector.every(Number.isFinite),
          ),
      )
    )
      throw new Error("demoInvalidCandidateAsset");
  }
  if (
    !data.restJoints.every(
      (joint) => joint.length === 3 && joint.every(Number.isFinite),
    ) ||
    data.parents.some(
      (parent, index) =>
        !Number.isInteger(parent) ||
        (index === 0 ? parent !== -1 : parent < 0 || parent >= index),
    )
  )
    throw new Error("demoInvalidCandidateAsset");
  return data;
}
