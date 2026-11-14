import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(
  new URL("../src/demo/demo.css", import.meta.url),
  "utf8",
);
const start = css.indexOf("可访问性覆盖");
const override = start < 0 ? "" : css.slice(start);
const SURFACES = ["#fffefa", "#f6f5f0", "#e7eeea"];

function luminance(hex) {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function ratio(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function token(name) {
  const m = override.match(
    new RegExp("--" + name + ":[ ]*(#[0-9a-f]{6})", "i"),
  );
  assert.ok(m, "missing override token --" + name);
  return m[1];
}

test("accessibility override block exists in demo.css", () => {
  assert.ok(start >= 0);
});

test("muted and warning text keep WCAG AA contrast on every surface", () => {
  for (const name of ["muted", "warn"]) {
    const color = token(name);
    for (const surface of SURFACES) {
      assert.ok(
        ratio(color, surface) >= 4.5,
        name + " " + color + " on " + surface + " is below 4.5:1",
      );
    }
  }
});

test("override font sizes never go below 13px and input text is large", () => {
  const sizes = [...override.matchAll(/font-size:[ ]*([0-9]+)px/g)].map((m) =>
    Number(m[1]),
  );
  assert.ok(sizes.length > 0);
  assert.ok(Math.min(...sizes) >= 13);
  assert.ok(sizes.includes(16));
  assert.ok(sizes.includes(20));
});

test("buttons and links have a touch target of at least 44px", () => {
  assert.match(override, /min-height:[ ]*44px/);
});

test("system preferences for contrast and reduced motion are honored", () => {
  assert.match(override, /prefers-contrast:[ ]*more/);
  assert.match(override, /prefers-reduced-motion:[ ]*reduce/);
  assert.match(override, /animation:[ ]*none !important/);
  assert.match(override, /transition:[ ]*none !important/);
});
