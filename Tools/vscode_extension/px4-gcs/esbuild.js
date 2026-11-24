// esbuild bundler for the Px4-GCS extension.
// Two bundles: the Node extension host entry and the browser dashboard page.
const esbuild = require('esbuild');
const fs = require('fs');
const path = require('path');

const isWatch = process.argv.includes('--watch');
const OUT_DIR = 'dist';

/** @type {import('esbuild').BuildOptions} */
const extensionOptions = {
  entryPoints: ['src/extension.ts'],
  bundle: true,
  outfile: path.join(OUT_DIR, 'extension.js'),
  external: ['vscode'],
  format: 'cjs',
  platform: 'node',
  target: 'es2022',
  sourcemap: true,
  minify: false,
};

/** The dashboard runs in the webview browser context; its libraries are bundled into it. */
const dashboardOptions = {
  entryPoints: ['src/webview/dashboard-main.ts'],
  bundle: true,
  outfile: path.join(OUT_DIR, 'dashboard.js'),
  format: 'iife',
  platform: 'browser',
  target: 'es2022',
  sourcemap: true,
  minify: true,
};

/** Style sheets that ship beside the bundles (resolved only when the package is installed). */
const STYLE_SHEETS = [
  ['@xterm/xterm/package.json', 'css/xterm.css', 'xterm.css'],
  ['uplot/package.json', 'dist/uPlot.min.css', 'uplot.css'],
];

function copyStyleSheets() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  for (const [pkg, rel, out] of STYLE_SHEETS) {
    let root;
    try {
      root = path.dirname(require.resolve(pkg));
    } catch {
      continue;
    }
    fs.copyFileSync(path.join(root, rel), path.join(OUT_DIR, out));
  }
}

async function main() {
  copyStyleSheets();
  if (isWatch) {
    await (await esbuild.context(extensionOptions)).watch();
    await (await esbuild.context(dashboardOptions)).watch();
    console.log('[esbuild] Watching for changes...');
  } else {
    await esbuild.build(extensionOptions);
    await esbuild.build(dashboardOptions);
    console.log('[esbuild] Build complete: extension.js, dashboard.js');
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
