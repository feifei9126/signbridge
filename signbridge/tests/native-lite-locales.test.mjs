import assert from "node:assert/strict";
import test from "node:test";
import { LOCALES } from "../src/i18n/locales.js";

const KEYS = [
  "nativeLiteStartFailed",
  "nativeLiteInstallPlugin",
  "nativeLiteInstallHelp",
  "nativeLiteInstallDone",
  "nativeLiteOpenExtensions",
  "nativeLiteChromeMissing",
];

for (const locale of ["zh-CN", "en"]) {
  test(`native lite labels exist in ${locale}`, () => {
    const labels = LOCALES[locale]?.modelDemo;
    assert.ok(labels, `${locale} modelDemo missing`);
    for (const key of KEYS) {
      assert.equal(typeof labels[key], "string", `${locale}.${key} missing`);
      assert.ok(labels[key].trim().length > 0, `${locale}.${key} empty`);
    }
  });
}
