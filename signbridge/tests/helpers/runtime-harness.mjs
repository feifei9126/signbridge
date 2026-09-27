import { build } from "esbuild";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

export async function bundleRuntime(entry, dependencies = {}) {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(entry, import.meta.url))],
    bundle: true,
    format: "iife",
    write: false,
    plugins: [
      {
        name: "test-dependencies",
        setup(builder) {
          builder.onResolve({ filter: /.*/ }, (args) => {
            if (dependencies[args.path])
              return { path: args.path, namespace: "test" };
          });
          builder.onLoad({ filter: /.*/, namespace: "test" }, (args) => ({
            contents: dependencies[args.path]
              .map(
                (name) =>
                  `export const ${name} = globalThis.testDependencies.${name};`,
              )
              .join("\n"),
          }));
        },
      },
    ],
  });
  return result.outputFiles[0].text;
}

export function runRuntime(code, globals) {
  const context = vm.createContext({
    console: { log() {}, warn() {}, error() {} },
    Blob,
    AbortController,
    setTimeout,
    clearTimeout,
    ...globals,
  });
  vm.runInContext(code, context);
  return context;
}

export function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

export async function flushTasks() {
  await new Promise((resolve) => setImmediate(resolve));
}
