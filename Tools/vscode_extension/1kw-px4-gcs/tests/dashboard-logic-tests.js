// Dashboard logic without a browser: formatters, instrument math, parameter
// windowing and search, stream-demand reference counting, the content
// security policy, and a source scan that keeps markup sinks out of the
// webview (every vehicle string must reach the page as a text node).
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { tempDir } = require('./bridge-test-harness');

const MODULES = [
  'src/webview/format/telemetry-format', 'src/webview/fly/attitude-indicator', 'src/webview/fly/heading-tape',
  'src/webview/fly/status-log', 'src/webview/parameters/parameter-table', 'src/webview/console/console-paste-guard',
  'src/webview/inspector/inspector-tab', 'src/webview/sensors/sensor-bench', 'src/webview/connection-bar',
  'src/webview/webview-state', 'src/dashboard/stream-demand', 'src/dashboard/dashboard-csp',
  'src/console/console-line-assembler',
];

function buildLogic(extDir) {
  const out = path.join(tempDir('px4-gcs-dashboard-'), 'logic.js');
  require('esbuild').buildSync({
    stdin: { contents: MODULES.map((m) => `export * from './${m}';`).join('\n'), resolveDir: extDir, loader: 'ts' },
    bundle: true, platform: 'node', format: 'cjs', target: 'node18', outfile: out, logLevel: 'silent',
  });
  return require(out);
}

const near = (actual, expected, label, eps = 1e-9) => assert.ok(Math.abs(actual - expected) < eps, `${label}: ${actual} != ${expected}`);

function formatters(L) {
  assert.equal(L.fmt(-0.00001, 1, 'm'), '0.0 m', 'negative zero is normalised');
  assert.equal(L.fmt(undefined, 1), L.DASH);
  assert.equal(L.fmt(NaN, 1), L.DASH);
  assert.equal(L.wrap360(-10), 350);
  assert.equal(L.wrap180(190), -170);
  assert.equal(L.ageText(400), '0.4 s');
  assert.equal(L.ageText(30000), '30 s');
  assert.equal(L.severityName(3), 'ERROR');
  assert.equal(L.severityClass(2), 'error');
  assert.equal(L.severityClass(4), 'warn');
  assert.equal(L.severityClass(6), 'info');
  assert.equal(L.gpsFixName(3), '3D fix');
  assert.equal(L.formatParamValue(3.9, 'INT32'), '3');
  assert.equal(L.formatParamValue(0.1 + 0.2, 'REAL32'), '0.3');
  assert.equal(L.formatParamValue(1e-6, 'REAL32'), '1.0000e-6');
  assert.equal(L.vec3([1, 2, 3], 1), '1.0, 2.0, 3.0');
  assert.equal(L.vec3([1, 2]), L.DASH);
  assert.equal(L.linkText({ transport: 'serial', port: '/dev/ttyUSB0', baud: 57600, systemId: 1 }), '/dev/ttyUSB0 @ 57600 · system 1');
  assert.equal(L.linkText({ transport: 'udp', host: '127.0.0.1', udpPort: 14550 }), 'UDP 127.0.0.1:14550');
  console.log('  ok formatters');
}

function instruments(L) {
  const level = L.horizonTransform(0, 0);
  near(level.rotateDeg, 0, 'level roll');
  near(level.offsetPx, 0, 'level pitch');
  const banked = L.horizonTransform(Math.PI / 6, Math.PI / 18);
  near(banked.rotateDeg, -30, 'right roll rotates the horizon left', 1e-6);
  near(banked.offsetPx, 10 * L.PX_PER_DEG, 'nose up moves the horizon down', 1e-6);
  near(L.horizonTransform(0, Math.PI).offsetPx, 90 * L.PX_PER_DEG, 'pitch is clamped to 90°', 1e-6);
  const eased = L.easePose({ rotateDeg: 170, offsetPx: 0 }, { rotateDeg: -170, offsetPx: 10 }, 0.5);
  near(eased.rotateDeg, 180, 'easing takes the short way across ±180', 1e-6);
  near(eased.offsetPx, 5, 'offset eases linearly');

  const north = L.headingTicks(0);
  assert.equal(north.length, 9, 'a ±45° window holds the nine 10° ticks from -40 to 40');
  assert.deepEqual(north.find((t) => t.offset === 0), { deg: 0, offset: 0, label: 'N' });
  assert.ok(north.some((t) => t.deg === 320 && t.offset === -40), 'ticks wrap below north');
  assert.ok(north.some((t) => t.deg === 30 && t.label === '30'), 'numbers every 30°');
  const east = L.headingTicks(95);
  assert.ok(east.every((t) => Math.abs(t.offset) <= 45), 'ticks stay inside the window');
  assert.equal(east.find((t) => t.deg === 90).label, 'E');
  assert.ok(east.some((t) => t.deg === 50 && t.label === null), 'minor ticks have no label');
  console.log('  ok attitude and heading geometry');
}

function parameters(L) {
  assert.deepEqual(L.visibleRange(0, 240, 24, 1400, 8), { start: 0, end: 18 });
  assert.deepEqual(L.visibleRange(24 * 100, 240, 24, 1400, 8), { start: 92, end: 118 });
  assert.deepEqual(L.visibleRange(24 * 1399, 240, 24, 1400, 8), { start: 1391, end: 1400 }, 'clamped at the end');
  assert.deepEqual(L.visibleRange(0, 240, 24, 0, 8), { start: 0, end: 0 }, 'empty list');
  assert.deepEqual(L.visibleRange(-50, 240, 24, 5, 8), { start: 0, end: 5 }, 'overscroll at the top');
  const params = ['MC_ROLL_P', 'MC_PITCH_P', 'MPC_XY_VEL_MAX', 'COM_ARM_WO_GPS', 'SYS_AUTOSTART']
    .map((name, index) => ({ name, index, type: 'REAL32', value: index }));
  assert.equal(L.filterParams(params, '').length, 5, 'empty search keeps all');
  assert.deepEqual(L.filterParams(params, 'mc_').map((p) => p.name), ['MC_ROLL_P', 'MC_PITCH_P'], 'case-insensitive');
  assert.deepEqual(L.filterParams(params, ' p  roll ').map((p) => p.name), ['MC_ROLL_P'], 'every term must match');
  assert.equal(L.filterParams(params, 'nothing').length, 0);
  assert.equal(L.progressText({ state: 'loading', received: 12, total: null }), 'Loading 12 / ?');
  assert.equal(L.progressText({ state: 'done', params, count: 5, missing: [3] }), '5 parameters, 1 missing');
  console.log('  ok parameter windowing and search');
}

function consoleAndLogs(L) {
  assert.equal(L.pasteLineCount('ver all'), 1);
  assert.equal(L.pasteLineCount('ver all\n'), 1, 'a trailing line end is not a second line');
  assert.equal(L.pasteLineCount('ver all\r\nps\nfree'), 3);
  assert.equal(L.pasteToShell('a\r\nb\nc'), 'a\rb\rc');
  const a = new L.ConsoleLineAssembler();
  assert.deepEqual(a.feed('ver al'), []);
  assert.deepEqual(a.feed('l\r'), ['ver all']);
  assert.deepEqual(a.feed('lx\x7fs\r\n'), ['ls'], 'backspace edits; CRLF ends one line');
  assert.deepEqual(a.feed('\x1b[A\r'), ['<ESC>[A'], 'escape sequences are tokens');
  const entries = [0, 3, 4, 6, 7].map((severity) => ({ ts: 0, severity, text: `s${severity}` }));
  assert.deepEqual(L.filterStatus(entries, 4).map((e) => e.severity), [0, 3, 4]);
  assert.match(L.statusLine(entries[1]), /^\d\d:\d\d:\d\d ERROR s3$/);
  const rows = [{ name: 'B', id: 2, component: 1 }, { name: 'A', id: 9, component: 2 }, { name: 'A', id: 9, component: 1 }];
  assert.deepEqual(L.sortInspector(rows).map(L.inspectorKey), ['9:1', '9:2', '2:1']);
  assert.equal(L.lastValueText(null), '');
  assert.equal(L.lastValueText({ x: 1 }), '{\n  "x": 1\n}');
  assert.equal(L.streamNoteText('raised'), null);
  assert.match(L.streamNoteText('refused', 'no current stream'), /^Rate not raised: no current stream/);
  console.log('  ok console paste, line journal, status filter, inspector order');
}

function webviewState(L) {
  let now = 1000;
  const s = new L.WebviewState(() => now);
  s.apply({ type: 'connection', connection: 'connected', link: null, stale: false });
  for (let i = 0; i < 10; i += 1) {
    s.apply({ type: 'values', values: { attitude: { ts: i, data: { roll: i } } }, stale: false });
    now += 100;
  }
  s.apply({ type: 'values', values: { attitude: { ts: 9, data: { roll: 9 } } }, stale: false });
  near(s.rateHz('attitude'), 2, 'ten distinct samples in five seconds; a repeat is not counted');
  assert.equal(s.isStale('attitude'), false);
  now += 2500;
  assert.equal(s.isStale('attitude'), true, 'no new sample for 2 s greys the value');
  assert.equal(s.isStale('missing'), true);
  s.apply({ type: 'connection', connection: 'connecting', link: null, stale: false });
  assert.equal(s.values.size, 0, 'a new connection clears old values');
  console.log('  ok webview state: rate, stale, reset');
}

async function streamDemand(L) {
  const calls = [];
  let refuse = new Set();
  const port = {
    request: async (message, intervalUs) => {
      calls.push(['request', message, intervalUs]);
      if (refuse.has(message)) throw new Error('no current stream');
    },
    release: async (message) => { calls.push(['release', message]); },
  };
  const notes = [];
  const demand = new L.StreamDemand(port, (note) => notes.push(note));
  await demand.acquire('sensors', [{ message: 105, intervalUs: 100000 }]);
  await demand.acquire('plots', [{ message: 105, intervalUs: 100000 }]);
  await demand.acquire('sensors', [{ message: 105, intervalUs: 100000 }]);
  assert.deepEqual(calls, [['request', 105, 100000]], 'one request for two owners; same-set acquire is a no-op');
  assert.equal(demand.refCount(105), 2);
  await demand.releaseOwner('sensors');
  assert.equal(calls.length, 1, 'still held by the second owner');
  await demand.releaseOwner('plots');
  assert.deepEqual(calls[1], ['release', 105], 'the last owner releases');
  refuse = new Set([29]);
  await demand.acquire('sensors', [{ message: 29, intervalUs: 200000 }]);
  assert.ok(notes.some((n) => n.message === 29 && n.outcome === 'refused' && /no current stream/.test(n.reason)));
  await demand.releaseOwner('sensors');
  assert.ok(!calls.some((c) => c[0] === 'release' && c[1] === 29), 'a refused request is never released');
  await demand.acquire('sensors', [{ message: 105, intervalUs: 100000 }]);
  demand.reset();
  assert.equal(demand.refCount(105), 0, 'reset forgets demand without sending (the sidecar restores on disconnect)');
  console.log('  ok stream demand reference counting');
}

function csp(L) {
  const policy = L.buildDashboardCsp('vscode-webview://abc', 'N0nce');
  const parts = policy.split(';').map((p) => p.trim());
  assert.equal(parts[0], "default-src 'none'");
  assert.ok(!/unsafe-eval/.test(policy), 'no unsafe-eval');
  const script = parts.find((p) => p.startsWith('script-src'));
  assert.equal(script, "script-src 'nonce-N0nce'", 'scripts need the nonce and nothing else');
  assert.ok(!/https?:/.test(policy), 'no remote origin');
  const page = L.dashboardHtml({ cspSource: 'vscode-webview://abc', nonce: 'N0nce', scriptUri: 'x.js?a="b"', styleUris: ['s.css'] });
  assert.match(page, /<script nonce="N0nce" src="x\.js\?a=&quot;b&quot;"><\/script>/, 'attributes are escaped');
  assert.equal((page.match(/<script/g) || []).length, 1, 'one script element');
  assert.ok(L.createNonce() !== L.createNonce(), 'a fresh nonce per load');
  console.log('  ok content security policy');
}

function sourceScan(extDir) {
  const SINKS = /\b(innerHTML|outerHTML|insertAdjacentHTML|document\.write)\b|\beval\s*\(|new Function\s*\(/;
  const files = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith('.ts')) files.push(full);
    }
  };
  walk(path.join(extDir, 'src', 'webview'));
  walk(path.join(extDir, 'src', 'dashboard'));
  const hits = files.filter((f) => SINKS.test(fs.readFileSync(f, 'utf8'))).map((f) => path.relative(extDir, f));
  assert.deepEqual(hits, [], `markup sinks found: ${hits.join(', ')}`);
  console.log(`  ok no markup sinks in ${files.length} dashboard source files`);
}

async function run({ EXT_DIR }) {
  const L = buildLogic(EXT_DIR);
  formatters(L);
  instruments(L);
  parameters(L);
  consoleAndLogs(L);
  webviewState(L);
  await streamDemand(L);
  csp(L);
  sourceScan(EXT_DIR);
}

module.exports = { run };
