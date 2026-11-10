// esbuild bundler for PX4/NuttX Firmware Workspace extension
const esbuild = require('esbuild');
const fs = require('fs');
const path = require('path');

const isWatch = process.argv.includes('--watch');

/** @type {import('esbuild').BuildOptions} */
const buildOptions = {
  entryPoints: ['src/extension.ts'],
  bundle: true,
  outfile: 'dist/extension.js',
  external: ['vscode'],
  format: 'cjs',
  platform: 'node',
  target: 'es2022',
  sourcemap: true,
  minify: false,
};

/** The RTT Monitor page runs in a browser context; xterm is bundled into it. */
const webviewOptions = {
  entryPoints: ['src/rtt-monitor/webview/rtt-monitor-webview.ts'],
  bundle: true,
  outfile: 'dist/rtt-monitor-webview.js',
  format: 'iife',
  platform: 'browser',
  target: 'es2022',
  sourcemap: true,
  minify: true,
};

function copyXtermCss() {
  const source = path.join(path.dirname(require.resolve('@xterm/xterm/package.json')), 'css', 'xterm.css');
  fs.mkdirSync('dist', { recursive: true });
  fs.copyFileSync(source, path.join('dist', 'xterm.css'));
}

async function main() {
  copyXtermCss();
  if (isWatch) {
    const ctx = await esbuild.context(buildOptions);
    await ctx.watch();
    await (await esbuild.context(webviewOptions)).watch();
    console.log('[esbuild] Watching for changes...');
  } else {
    await esbuild.build(buildOptions);
    await esbuild.build(webviewOptions);
    console.log('[esbuild] Build complete: dist/extension.js, dist/rtt-monitor-webview.js');
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
