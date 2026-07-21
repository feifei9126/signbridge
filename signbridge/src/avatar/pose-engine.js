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

export { deg, frm };
