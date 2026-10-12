// Browser RAF timestamps can precede a synchronous clip compilation's completion.
export function frameDelta(timestamp, previous) {
  return Math.max(0, Math.min((timestamp - previous) / 1000, 0.1));
}
