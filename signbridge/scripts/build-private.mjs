// Separate, allowlisted client build. Never copy local-data or legacy bundles.
import { build } from "esbuild";
import {
  copyFileSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const output = resolve(
  process.env.SIGNBRIDGE_PRIVATE_BUILD_DIR || join(root, "dist-private"),
);
// mkdir without recursive/exist_ok is intentional: never erase previous evidence.
mkdirSync(output);
mkdirSync(join(output, "private"));
for (const file of ["index.html", "client.css"])
  copyFileSync(join(root, "src/private", file), join(output, "private", file));
for (const [entry, target] of [
  ["client.js", "private/client.js"],
  ["worker.js", "worker.js"],
]) {
  await build({
    entryPoints: [join(root, "src/private", entry)],
    outfile: join(output, target),
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "chrome116",
    minify: true,
    sourcemap: false,
    legalComments: "none",
  });
}
writeFileSync(
  join(output, "manifest.json"),
  JSON.stringify(
    {
      manifest_version: 3,
      name: "SignBridge Private Research",
      version: "0.1.2",
      minimum_chrome_version: "116",
      action: { default_title: "SignBridge Private Research" },
      background: { service_worker: "worker.js", type: "module" },
      host_permissions: ["http://127.0.0.1/*"],
      content_security_policy: {
        extension_pages:
          "default-src 'self'; script-src 'self'; style-src 'self'; connect-src http://127.0.0.1:*; object-src 'none'; base-uri 'none'",
      },
    },
    null,
    2,
  ) + "\n",
);
const files = {};
for (const name of readdirSync(output, { recursive: true })) {
  if (name === "private") continue;
  files[name] = createHash("sha256")
    .update(readFileSync(join(output, name)))
    .digest("hex");
}
writeFileSync(
  join(output, "BUILD.json"),
  JSON.stringify(
    {
      schema: "signbridge-private-client-build-v1",
      created_at: new Date().toISOString(),
      profile: "private-client",
      authored_dictionary_included: false,
      private_assets_included: false,
      csl_translation_trained: false,
      files,
    },
    null,
    2,
  ) + "\n",
);
console.log("Private client built: " + output);
