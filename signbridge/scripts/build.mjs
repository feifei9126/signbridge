import * as esbuild from 'esbuild';
import { copyFileSync, mkdirSync, writeFileSync, existsSync, readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');
const DIST = join(ROOT, 'dist');

function dp(...parts) { const p = join(DIST, ...parts); mkdirSync(dirname(p), { recursive: true }); return p; }

function genIcons() {
  for (const s of [16, 48, 128]) {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${s}" height="${s}" viewBox="0 0 128 128"><rect width="128" height="128" rx="24" fill="#4F46E5"/><text x="64" y="80" text-anchor="middle" font-size="60" fill="white" font-family="sans-serif">🤟</text></svg>`;
    writeFileSync(dp(`icons/icon${s}.svg`), svg);
    writeFileSync(dp(`icons/icon${s}.png`), svg);
  }
}

async function bundle(entry, outfile, opts = {}) {
  await esbuild.build({
    entryPoints: [join(ROOT, 'src', entry)],
    outfile: dp(outfile),
    bundle: true,
    format: opts.format || 'esm',
    globalName: opts.globalName,
    platform: 'browser',
    target: 'es2022',
    sourcemap: false,
    minify: true,
    legalComments: 'none',
  });
  console.log(`  ✓ ${entry} → ${outfile}`);
}

async function build() {
  console.log('\n🔵 SignBridge Build\n');
  mkdirSync(DIST, { recursive: true });

  copyFileSync(join(ROOT, 'manifest.json'), dp('manifest.json'));
  console.log('  ✓ manifest.json');
  genIcons();
  console.log('  ✓ icons');

  await bundle('background/worker.js', 'background/worker.js');
  await bundle('content/injector.js', 'content/injector.js', { format: 'iife' });
  const css = join(ROOT, 'src/content/overlay.css');
  if (existsSync(css)) copyFileSync(css, dp('content/overlay.css'));
  console.log('  ✓ content/overlay.css');

  // === Avatar: official THREE ES modules ===

  // Copy three.module.js (untouched, no esbuild)
  copyFileSync(join(ROOT, 'node_modules/three/build/three.module.js'), dp('avatar/three.module.js'));
  console.log('  ✓ three.module.js');

  // Copy & patch GLTFLoader.js — replace bare "three" import with relative path
  const gltfSrc = readFileSync(join(ROOT, 'node_modules/three/examples/jsm/loaders/GLTFLoader.js'), 'utf8');
  mkdirSync(dp('avatar/jsm/loaders'), { recursive: true });
  writeFileSync(dp('avatar/jsm/loaders/GLTFLoader.js'), gltfSrc.replace(/from\s+['"]three['"]/g, "from '../../three.module.js'"));
  console.log('  ✓ jsm/loaders/GLTFLoader.js');

  // Copy & patch BufferGeometryUtils.js
  const bguSrc = readFileSync(join(ROOT, 'node_modules/three/examples/jsm/utils/BufferGeometryUtils.js'), 'utf8');
  mkdirSync(dp('avatar/jsm/utils'), { recursive: true });
  writeFileSync(dp('avatar/jsm/utils/BufferGeometryUtils.js'), bguSrc.replace(/from\s+['"]three['"]/g, "from '../../three.module.js'"));
  console.log('  ✓ jsm/utils/BufferGeometryUtils.js');

  // Copy & patch FBXLoader.js
  const fbxSrc = readFileSync(join(ROOT, 'node_modules/three/examples/jsm/loaders/FBXLoader.js'), 'utf8');
  mkdirSync(dp('avatar/jsm/loaders'), { recursive: true });
  writeFileSync(dp('avatar/jsm/loaders/FBXLoader.js'), fbxSrc.replace(/from\s+['"]three['"]/g, "from '../../three.module.js'"));
  console.log('  ✓ jsm/loaders/FBXLoader.js');

  // iframe-bundle.js — BUNDLED with gesture data to avoid Chrome ES module caching
  const iframeSrc = join(ROOT, 'src/avatar/iframe-bundle.js');
  if (existsSync(iframeSrc)) {
    await esbuild.build({
      entryPoints: [iframeSrc],
      outfile: dp('avatar/iframe-bundle.js'),
      bundle: true,
      external: ['./three.module.js', './jsm/loaders/GLTFLoader.js'],
      format: 'esm',
      platform: 'browser',
      target: 'es2022',
      sourcemap: false,
      minify: false,
      legalComments: 'none',
    });
    console.log('  ✓ iframe-bundle.js (bundled with gesture data)');
  }

  ["sign-language-data.js", "pose-engine.js"].forEach((f) => {
    const s = join(ROOT, "src/avatar/" + f);
    if (existsSync(s)) {
      copyFileSync(s, dp("avatar/" + f));
      console.log("  ✓ avatar/" + f);
    }
  });

  // avatar-frame.html
  const frameSrc = join(ROOT, 'src/avatar/avatar-frame.html');
  if (existsSync(frameSrc)) {
    let html = readFileSync(frameSrc, 'utf8');
    html = html.replace('src="iframe-bundle.js"', 'src="iframe-bundle.js?v=" + stamp + ""');
    writeFileSync(dp('avatar/avatar-frame.html'), html);
  }
  console.log('  ✓ avatar/avatar-frame.html (v=" + stamp + ")');

  // Page agent
  await bundle('avatar/page-agent.js', 'avatar/page-agent.js', { format: 'iife' });

  // Popup
  const ph = join(ROOT, 'src/popup/index.html');
  if (existsSync(ph)) copyFileSync(ph, dp('popup/index.html'));
  const pc = join(ROOT, 'src/popup/popup.css');
  if (existsSync(pc)) copyFileSync(pc, dp('popup/popup.css'));
  console.log('  ✓ popup/{index.html,popup.css}');
  await bundle('popup/popup.js', 'popup/popup.js');
  await bundle('utils/config.js', 'utils/config.js');
  await bundle('i18n/locales.js', 'i18n/locales.js');

  console.log('\n✅ Build complete!\n');
}

build().catch(e => { console.error('Build failed:', e); process.exit(1); });
