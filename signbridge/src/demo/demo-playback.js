// Browser RAF timestamps can precede a synchronous clip compilation's completion.
export function frameDelta(timestamp, previous) {
  return Math.max(0, Math.min((timestamp - previous) / 1000, 0.1));
}
export function transitionAmount(seconds, duration = 0.18) {
  const t = Math.max(0, Math.min(1, seconds / duration));
  return t * t * (3 - 2 * t);
}
export function restTransition(rig) {
  const from = rig.capture();
  rig.reset();
  const to = rig.capture();
  rig.interpolate(from, from, 1);
  return { from, to, time: 0 };
}
