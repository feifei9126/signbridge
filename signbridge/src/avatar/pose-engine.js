/**
 * PoseEngine — 姿态工具函数
 * 提供 deg/frm/mkPose 等基础工具
 */
function deg(x, y, z) {
  const d = Math.PI / 180;
  return { x: (x || 0) * d, y: (y || 0) * d, z: (z || 0) * d };
}

function frm(pose, dur) {
  return { value: pose, duration: dur || 0.8 };
}

function motionClip(id, frames, metadata = {}) {
  if (!id || !Array.isArray(frames) || frames.length === 0) {
    throw new TypeError("A motion clip requires an id and at least one frame.");
  }
  return {
    id,
    version: 1,
    space: "humanoid-local-v1",
    frames,
    metadata,
  };
}

export { deg, frm, motionClip };
