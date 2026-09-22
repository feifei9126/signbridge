import { HUMANOID_BONES, canonicalizePose } from "./humanoid-rig.js";

const MAX_MOTION_BYTES = 2 * 1024 * 1024;
const MAX_MOTION_FRAMES = 240;
const knownBones = new Set(HUMANOID_BONES);

function invalid(detail, message = "motionInvalidData") {
  const error = new Error(message);
  error.detail = detail;
  throw error;
}

function plainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function boundedText(value, field, limit = 100) {
  if (typeof value !== "string" || !value.trim() || value.length > limit)
    invalid(field);
  return value.trim();
}

function textList(value, field, max = 20) {
  if (!Array.isArray(value) || value.length > max) invalid(field);
  return [...new Set(value.map((text) => boundedText(text, field)))];
}

function createRigBinding(rig) {
  if (!rig?.rest || !rig?.profile) invalid("rig", "motionModelNotReady");
  const rest = Object.keys(rig.rest)
    .sort()
    .map((name) => {
      const bone = rig.bones[name];
      const rotation = rig.rest[name].rotation;
      return [
        name,
        bone.name,
        bone.parent?.name || "",
        rotation.order,
        ...[
          rotation.x,
          rotation.y,
          rotation.z,
          ...bone.position.toArray(),
          ...bone.scale.toArray(),
        ].map((value) => Number(value.toFixed(9))),
      ];
    });
  return { profile: rig.profile.id, rest: JSON.stringify(rest) };
}

function validateMotionAsset(input, rig) {
  if (
    !plainObject(input) ||
    input.type !== "signbridge-motion" ||
    input.version !== 1 ||
    input.space !== "humanoid-local-v1" ||
    input.unit !== "radians"
  )
    invalid("type/version/space/unit");
  const id = boundedText(input.id, "id", 90);
  if (!/^custom_[a-zA-Z0-9_-]+$/.test(id)) invalid("id");
  const binding = createRigBinding(rig);
  if (
    input.rig?.profile !== binding.profile ||
    input.rig?.rest !== binding.rest
  )
    invalid("rig", "motionRigMismatch");
  if (
    !Array.isArray(input.frames) ||
    !input.frames.length ||
    input.frames.length > MAX_MOTION_FRAMES
  )
    invalid("frames");
  let total = 0;
  const frames = input.frames.map((frame, index) => {
    if (
      !plainObject(frame?.value) ||
      !Number.isFinite(frame.duration) ||
      frame.duration < 0.05 ||
      frame.duration > 10
    )
      invalid(`frames[${index}]`);
    total += frame.duration;
    const value = {};
    for (const [name, rotation] of Object.entries(frame.value)) {
      if (!knownBones.has(name) || !rig.bones[name] || !plainObject(rotation))
        invalid(`frames[${index}].${name}`);
      for (const axis of ["x", "y", "z"]) {
        if (
          !Number.isFinite(rotation[axis]) ||
          Math.abs(rotation[axis]) > Math.PI * 2
        )
          invalid(`${name}.${axis}`);
      }
      value[name] = { x: rotation.x, y: rotation.y, z: rotation.z };
    }
    return { value, duration: frame.duration };
  });
  if (total > 120) invalid("duration > 120s");
  return {
    type: "signbridge-motion",
    version: 1,
    id,
    gloss: boundedText(input.gloss, "gloss"),
    texts: textList(input.texts, "texts"),
    tags: textList(input.tags, "tags"),
    space: "humanoid-local-v1",
    unit: "radians",
    rig: binding,
    frames,
  };
}

function createMotionAsset(rig, frames, metadata) {
  return validateMotionAsset(
    {
      ...metadata,
      type: "signbridge-motion",
      version: 1,
      space: "humanoid-local-v1",
      unit: "radians",
      rig: createRigBinding(rig),
      frames,
    },
    rig,
  );
}

function parseMotionAsset(text, rig) {
  if (typeof text !== "string" || new Blob([text]).size > MAX_MOTION_BYTES)
    invalid("file size");
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    invalid("JSON");
  }
  return validateMotionAsset(parsed, rig);
}

function serializeMotionAsset(asset, round = false) {
  return JSON.stringify(asset, (_key, value) => {
    if (round && typeof value === "number") return Number(value.toFixed(8));
    if (plainObject(value))
      return Object.fromEntries(
        Object.keys(value)
          .sort()
          .map((key) => [key, value[key]]),
      );
    return value;
  });
}

function motionIdentity(asset) {
  return serializeMotionAsset(asset, true);
}

function convertLegacyMotion(input, format, rig, metadata) {
  if (
    !["editor-degrees", "recorder-degrees", "absolute-radians"].includes(format)
  )
    invalid("legacy format");
  const source =
    format === "recorder-degrees"
      ? input?.frames
      : [{ pose: input, duration: 0.8 }];
  if (!Array.isArray(source) || source.length > MAX_MOTION_FRAMES)
    invalid("legacy frames");
  const frames = source.map((frame) => {
    if (!plainObject(frame?.pose)) invalid("legacy pose");
    const value = {};
    for (const [name, rotation] of Object.entries(
      canonicalizePose(frame.pose),
    )) {
      if (!rig.rest[name] || !plainObject(rotation)) invalid(name);
      value[name] = {};
      for (const axis of ["x", "y", "z"]) {
        if (!Number.isFinite(rotation[axis])) invalid(`${name}.${axis}`);
        value[name][axis] =
          format === "absolute-radians"
            ? rotation[axis] - rig.rest[name].rotation[axis]
            : (rotation[axis] * Math.PI) / 180;
      }
    }
    return { value, duration: frame.duration };
  });
  return createMotionAsset(rig, frames, metadata);
}

export {
  serializeMotionAsset,
  MAX_MOTION_BYTES,
  MAX_MOTION_FRAMES,
  createRigBinding,
  createMotionAsset,
  validateMotionAsset,
  parseMotionAsset,
  convertLegacyMotion,
  motionIdentity,
};
