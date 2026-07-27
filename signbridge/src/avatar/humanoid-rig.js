const HUMANOID_BONES = Object.freeze([
  "root",
  "body",
  "hips",
  "spine",
  "chest",
  "upperChest",
  "neck",
  "neck2",
  "neck3",
  "head",
  "rightShoulder",
  "rightUpperArm",
  "rightLowerArm",
  "rightHand",
  "leftShoulder",
  "leftUpperArm",
  "leftLowerArm",
  "leftHand",
  "rightThumbMetacarpal",
  "rightThumbProximal",
  "rightThumbDistal",
  "rightIndexProximal",
  "rightIndexIntermediate",
  "rightIndexDistal",
  "rightMiddleProximal",
  "rightMiddleIntermediate",
  "rightMiddleDistal",
  "rightRingProximal",
  "rightRingIntermediate",
  "rightRingDistal",
  "rightLittleProximal",
  "rightLittleIntermediate",
  "rightLittleDistal",
  "leftThumbMetacarpal",
  "leftThumbProximal",
  "leftThumbDistal",
  "leftIndexProximal",
  "leftIndexIntermediate",
  "leftIndexDistal",
  "leftMiddleProximal",
  "leftMiddleIntermediate",
  "leftMiddleDistal",
  "leftRingProximal",
  "leftRingIntermediate",
  "leftRingDistal",
  "leftLittleProximal",
  "leftLittleIntermediate",
  "leftLittleDistal",
  "jaw",
  "leftUpperEyelid",
  "rightUpperEyelid",
  "leftLowerEyelid",
  "rightLowerEyelid",
]);

const REQUIRED_SIGNING_BONES = Object.freeze([
  "rightUpperArm",
  "rightLowerArm",
  "rightHand",
  "leftUpperArm",
  "leftLowerArm",
  "leftHand",
  "rightThumbMetacarpal",
  "rightThumbProximal",
  "rightThumbDistal",
  "rightIndexProximal",
  "rightIndexIntermediate",
  "rightIndexDistal",
  "rightMiddleProximal",
  "rightMiddleIntermediate",
  "rightMiddleDistal",
  "rightRingProximal",
  "rightRingIntermediate",
  "rightRingDistal",
  "rightLittleProximal",
  "rightLittleIntermediate",
  "rightLittleDistal",
  "leftThumbMetacarpal",
  "leftThumbProximal",
  "leftThumbDistal",
  "leftIndexProximal",
  "leftIndexIntermediate",
  "leftIndexDistal",
  "leftMiddleProximal",
  "leftMiddleIntermediate",
  "leftMiddleDistal",
  "leftRingProximal",
  "leftRingIntermediate",
  "leftRingDistal",
  "leftLittleProximal",
  "leftLittleIntermediate",
  "leftLittleDistal",
]);

const GODETTE_PROFILE = Object.freeze({
  id: "godette-v1",
  motionSpace: "humanoid-local-v1",
  bones: Object.freeze({
    root: ["Root_225"],
    body: ["Body_220"],
    hips: ["Hip_218"],
    spine: ["Spine_1_199"],
    chest: ["Spine_2_198"],
    upperChest: ["Ribcage_197"],
    neck: ["Neck_1_132"],
    neck2: ["Neck_2_131"],
    neck3: ["Neck_3_130"],
    head: ["Head_129"],
    rightShoulder: ["ClavicR_192", "Clavic.R_192"],
    rightUpperArm: ["Arm_Upper_1R_187", "Arm_Upper_1.R_187"],
    rightLowerArm: ["Arm_Lower_1R_185", "Arm_Lower_1.R_185"],
    rightHand: ["HandR_184", "Hand.R_184"],
    leftShoulder: ["ClavicL_162", "Clavic.L_162"],
    leftUpperArm: ["Arm_Upper_1L_157", "Arm_Upper_1.L_157"],
    leftLowerArm: ["Arm_Lower_1L_155", "Arm_Lower_1.L_155"],
    leftHand: ["HandL_154", "Hand.L_154"],
    rightThumbMetacarpal: ["ThumbR_178", "Thumb.R_178"],
    rightThumbProximal: ["ThumbR002_177", "Thumb.R.002_177"],
    rightThumbDistal: ["ThumbR001_176", "Thumb.R.001_176"],
    rightIndexProximal: ["Finger_1R_166", "Finger_1.R_166"],
    rightIndexIntermediate: ["Finger_1R002_165", "Finger_1.R.002_165"],
    rightIndexDistal: ["Finger_1R001_164", "Finger_1.R.001_164"],
    rightMiddleProximal: ["Finger_2R_169", "Finger_2.R_169"],
    rightMiddleIntermediate: ["Finger_2R002_168", "Finger_2.R.002_168"],
    rightMiddleDistal: ["Finger_2R001_167", "Finger_2.R.001_167"],
    rightRingProximal: ["Finger_3R_172", "Finger_3.R_172"],
    rightRingIntermediate: ["Finger_3R002_171", "Finger_3.R.002_171"],
    rightRingDistal: ["Finger_3R001_170", "Finger_3.R.001_170"],
    rightLittleProximal: ["Finger_4R_175", "Finger_4.R_175"],
    rightLittleIntermediate: ["Finger_4R002_174", "Finger_4.R.002_174"],
    rightLittleDistal: ["Finger_4R001_173", "Finger_4.R.001_173"],
    leftThumbMetacarpal: ["ThumbL_148", "Thumb.L_148"],
    leftThumbProximal: ["ThumbL002_147", "Thumb.L.002_147"],
    leftThumbDistal: ["ThumbL001_146", "Thumb.L.001_146"],
    leftIndexProximal: ["Finger_1L_136", "Finger_1.L_136"],
    leftIndexIntermediate: ["Finger_1L002_135", "Finger_1.L.002_135"],
    leftIndexDistal: ["Finger_1L001_134", "Finger_1.L.001_134"],
    leftMiddleProximal: ["Finger_2L_139", "Finger_2.L_139"],
    leftMiddleIntermediate: ["Finger_2L002_138", "Finger_2.L.002_138"],
    leftMiddleDistal: ["Finger_2L001_137", "Finger_2.L.001_137"],
    leftRingProximal: ["Finger_3L_142", "Finger_3.L_142"],
    leftRingIntermediate: ["Finger_3L002_141", "Finger_3.L.002_141"],
    leftRingDistal: ["Finger_3L001_140", "Finger_3.L.001_140"],
    leftLittleProximal: ["Finger_4L_145", "Finger_4.L_145"],
    leftLittleIntermediate: ["Finger_4L002_144", "Finger_4.L.002_144"],
    leftLittleDistal: ["Finger_4L001_143", "Finger_4.L.001_143"],
    jaw: ["Jaw_4"],
    leftUpperEyelid: ["Eyelid_Control_UpperL_14"],
    rightUpperEyelid: ["Eyelid_Control_UpperR_15"],
    leftLowerEyelid: ["Eyelid_Control_LowerL_16"],
    rightLowerEyelid: ["Eyelid_Control_LowerR_17"],
  }),
});

const LEGACY_BONE_ALIASES = Object.freeze({
  hip: "hips",
  ribcage: "upperChest",
  rShoulder: "rightShoulder",
  rUpperArm: "rightUpperArm",
  rForearm: "rightLowerArm",
  rHand: "rightHand",
  lShoulder: "leftShoulder",
  lUpperArm: "leftUpperArm",
  lForearm: "leftLowerArm",
  lHand: "leftHand",
  rthumb: "rightThumbMetacarpal",
  rindex: "rightIndexIntermediate",
  rmiddle: "rightMiddleIntermediate",
  rring: "rightRingIntermediate",
  rpinky: "rightLittleIntermediate",
  lthumb: "leftThumbMetacarpal",
  lindex: "leftIndexIntermediate",
  lmiddle: "leftMiddleIntermediate",
  lring: "leftRingIntermediate",
  lpinky: "leftLittleIntermediate",
  lUpperEyelid: "leftUpperEyelid",
  rUpperEyelid: "rightUpperEyelid",
  lLowerEyelid: "leftLowerEyelid",
  rLowerEyelid: "rightLowerEyelid",
});

function normalizeBoneName(name) {
  return String(name || "")
    .replace(/[._\s-]/g, "")
    .toLowerCase();
}

function canonicalizePose(pose = {}) {
  const canonical = {};
  for (const [name, rotation] of Object.entries(pose)) {
    canonical[LEGACY_BONE_ALIASES[name] || name] = rotation;
  }
  return canonical;
}

function indexSceneBones(root) {
  const exact = new Map();
  const normalized = new Map();
  const skeletons = new Set();
  root?.traverse?.((object) => {
    if (object.isBone) {
      exact.set(object.name, object);
      normalized.set(normalizeBoneName(object.name), object);
    }
    if (object.isSkinnedMesh && object.skeleton) skeletons.add(object.skeleton);
  });
  return { exact, normalized, skeletons: [...skeletons] };
}

function resolveProfileBones(root, profile = GODETTE_PROFILE) {
  const index = indexSceneBones(root);
  const bones = {};
  for (const [canonicalName, candidates] of Object.entries(profile.bones)) {
    for (const candidate of candidates) {
      const bone =
        index.exact.get(candidate) ||
        index.normalized.get(normalizeBoneName(candidate));
      if (bone) {
        bones[canonicalName] = bone;
        break;
      }
    }
  }
  return { bones, skeletons: index.skeletons };
}

function createHumanoidRig(root, profile = GODETTE_PROFILE) {
  const { bones, skeletons } = resolveProfileBones(root, profile);
  const rest = {};
  for (const [name, bone] of Object.entries(bones)) {
    rest[name] = {
      quaternion: bone.quaternion.clone(),
      rotation: {
        x: bone.rotation.x,
        y: bone.rotation.y,
        z: bone.rotation.z,
        order: bone.rotation.order,
      },
    };
  }

  function update() {
    for (const skeleton of skeletons) skeleton.update();
  }

  function createTargets(pose = {}) {
    const canonicalPose = canonicalizePose(pose);
    const targets = {};
    for (const [name, bone] of Object.entries(bones)) {
      const base = rest[name];
      const delta = canonicalPose[name];
      if (!delta) {
        targets[name] = base.quaternion.clone();
        continue;
      }
      const rotation = bone.rotation.clone();
      rotation.set(
        base.rotation.x + (delta.x || 0),
        base.rotation.y + (delta.y || 0),
        base.rotation.z + (delta.z || 0),
        base.rotation.order,
      );
      targets[name] = bone.quaternion.clone().setFromEuler(rotation);
    }
    return targets;
  }

  function capture() {
    const snapshot = {};
    for (const [name, bone] of Object.entries(bones)) {
      snapshot[name] = bone.quaternion.clone();
    }
    return snapshot;
  }

  function capturePose() {
    const pose = {};
    for (const [name, bone] of Object.entries(bones)) {
      const base = rest[name].rotation;
      pose[name] = {
        x: bone.rotation.x - base.x,
        y: bone.rotation.y - base.y,
        z: bone.rotation.z - base.z,
      };
    }
    return pose;
  }

  function interpolate(from, targets, amount) {
    for (const [name, bone] of Object.entries(bones)) {
      const start = from[name] || rest[name].quaternion;
      const target = targets[name] || rest[name].quaternion;
      bone.quaternion.copy(start).slerp(target, amount);
    }
    update();
  }

  function applyPose(pose) {
    const targets = createTargets(pose);
    for (const [name, bone] of Object.entries(bones)) {
      bone.quaternion.copy(targets[name]);
    }
    update();
  }

  function reset() {
    for (const [name, bone] of Object.entries(bones)) {
      bone.quaternion.copy(rest[name].quaternion);
    }
    update();
  }

  const missing = REQUIRED_SIGNING_BONES.filter((name) => !bones[name]);
  return {
    profile,
    bones,
    rest,
    missing,
    isSigningReady: missing.length === 0,
    createTargets,
    capture,
    capturePose,
    interpolate,
    applyPose,
    reset,
    update,
  };
}

export {
  GODETTE_PROFILE,
  HUMANOID_BONES,
  LEGACY_BONE_ALIASES,
  REQUIRED_SIGNING_BONES,
  canonicalizePose,
  createHumanoidRig,
  normalizeBoneName,
  resolveProfileBones,
};
