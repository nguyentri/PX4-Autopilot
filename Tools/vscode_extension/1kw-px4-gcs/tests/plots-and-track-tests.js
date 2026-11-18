// Plots and Track without a browser: the equirectangular projection against
// known geodesic distances, track source selection and the empty state, scale
// bars, distance and bearing text, the webview history mirror (decimation,
// cap, seeding), plot windowing, the host history request against the real
// sidecar with a circling peer, and the no-tiles source rules.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { Peer, PYTHON, PYTHON_DIR, freeUdpPort, tempDir, waitFor } = require('./bridge-test-harness');

function buildLogic(extDir) {
  const out = path.join(tempDir('px4-gcs-plots-'), 'plots.js');
  const modules = [
    'src/webview/track/track-projection', 'src/webview/track/track-tab', 'src/webview/history/session-history',
    'src/webview/plots/plot-series-catalog', 'src/webview/webview-state', 'src/dashboard/dashboard-messages',
    'src/dashboard/dashboard-router', 'src/connection/connection-controller', 'src/vehicle/vehicle-state-store',
    'src/session/session-journal',
  ];
  require('esbuild').buildSync({
    stdin: { contents: modules.map((m) => `export * from './${m}';`).join('\n'), resolveDir: extDir, loader: 'ts' },
    bundle: true, platform: 'node', format: 'cjs', target: 'node18', outfile: out, logLevel: 'silent',
  });
  return require(out);
}

/** Vincenty inverse on WGS84 (reference distance for the projection check). */
function vincenty(lat1, lon1, lat2, lon2) {
  const a = 6378137;
  const f = 1 / 298.257223563;
  const b = (1 - f) * a;
  const rad = Math.PI / 180;
  const L = (lon2 - lon1) * rad;
  const U1 = Math.atan((1 - f) * Math.tan(lat1 * rad));
  const U2 = Math.atan((1 - f) * Math.tan(lat2 * rad));
  const [sinU1, cosU1, sinU2, cosU2] = [Math.sin(U1), Math.cos(U1), Math.sin(U2), Math.cos(U2)];
  let lambda = L;
  let sinSigma; let cosSigma; let sigma; let cos2Alpha; let cos2SigmaM;
  for (let i = 0; i < 200; i += 1) {
    const sinL = Math.sin(lambda);
    const cosL = Math.cos(lambda);
    sinSigma = Math.hypot(cosU2 * sinL, cosU1 * sinU2 - sinU1 * cosU2 * cosL);
    if (sinSigma === 0) return 0;
    cosSigma = sinU1 * sinU2 + cosU1 * cosU2 * cosL;
    sigma = Math.atan2(sinSigma, cosSigma);
    const sinAlpha = (cosU1 * cosU2 * sinL) / sinSigma;
    cos2Alpha = 1 - sinAlpha * sinAlpha;
    cos2SigmaM = cos2Alpha === 0 ? 0 : cosSigma - (2 * sinU1 * sinU2) / cos2Alpha;
    const C = (f / 16) * cos2Alpha * (4 + f * (4 - 3 * cos2Alpha));
    const prev = lambda;
    lambda = L + (1 - C) * f * sinAlpha * (sigma + C * sinSigma * (cos2SigmaM + C * cosSigma * (-1 + 2 * cos2SigmaM ** 2)));
    if (Math.abs(lambda - prev) < 1e-13) break;
  }
  const u2 = (cos2Alpha * (a * a - b * b)) / (b * b);
  const A = 1 + (u2 / 16384) * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)));
  const B = (u2 / 1024) * (256 + u2 * (-128 + u2 * (74 - 47 * u2)));
  const dSigma = B * sinSigma * (cos2SigmaM + (B / 4) * (cosSigma * (-1 + 2 * cos2SigmaM ** 2)
    - (B / 6) * cos2SigmaM * (-3 + 4 * sinSigma ** 2) * (-3 + 4 * cos2SigmaM ** 2)));
  return b * A * (sigma - dSigma);
}

function projection(L) {
  for (const lat0 of [0, 10.5, 45, 60]) {
    const home = { lat: lat0, lon: 106.6 };
    for (const bearing of [0, 45, 90, 135, 200, 300]) {
      // A point about 1 km away: offset by degrees, then compare with Vincenty.
      const dn = Math.cos((bearing * Math.PI) / 180) * 1000 / 111000;
      const de = Math.sin((bearing * Math.PI) / 180) * 1000 / (111000 * Math.cos((lat0 * Math.PI) / 180));
      const p = { lat: lat0 + dn, lon: home.lon + de };
      const { east, north } = L.project(home, p);
      const err = Math.abs(Math.hypot(east, north) - vincenty(home.lat, home.lon, p.lat, p.lon));
      assert.ok(err < 1, `projection error ${err.toFixed(3)} m at lat ${lat0}, bearing ${bearing}`);
    }
  }
  const across = L.project({ lat: 0, lon: 179.999 }, { lat: 0, lon: -179.999 });
  assert.ok(across.east > 0 && across.east < 300, `antimeridian wraps east: ${across.east}`);
  console.log('  ok projection within 1 m of Vincenty over 1 km (lat 0..60, antimeridian)');
}

function distanceAndBearing(L) {
  const cases = [
    [{ east: 0, north: 100 }, 100, 0], [{ east: 100, north: 0 }, 100, 90], [{ east: 0, north: -50 }, 50, 180],
    [{ east: -30, north: 0 }, 30, 270], [{ east: 3, north: 4 }, 5, 36.87],
  ];
  for (const [p, distance, bearing] of cases) {
    const r = L.distanceBearing({ east: 0, north: 0 }, p);
    assert.ok(Math.abs(r.distance - distance) < 1e-6, `distance to ${JSON.stringify(p)}`);
    assert.ok(Math.abs(r.bearing - bearing) < 0.01, `bearing to ${JSON.stringify(p)}: ${r.bearing}`);
  }
  assert.equal(L.homeText({ east: 100, north: 0 }), 'From home: 100.0 m, bearing 090°');
  assert.equal(L.homeText({ east: 0, north: 5 }), 'From home: 5.0 m, bearing 000°');
  assert.equal(L.homeText({ east: -0.0001, north: 5 }), 'From home: 5.0 m, bearing 000°', '359.99° rounds to 000');
  assert.equal(L.homeText(undefined), 'No position yet.');
  console.log('  ok distance and bearing from home');
}

function scaleBars(L) {
  // Three zoom levels: 1 m/px, 0.05 m/px and 20 m/px with a 120 px limit.
  assert.deepEqual(L.scaleBar(1, 120), { meters: 100, pixels: 100, label: '100 m' });
  const fine = L.scaleBar(0.05, 120);
  assert.equal(fine.label, '5 m');
  assert.ok(Math.abs(fine.pixels - 100) < 1e-9);
  const coarse = L.scaleBar(20, 120);
  assert.equal(coarse.label, '2 km');
  assert.equal(coarse.pixels, 100);
  assert.equal(L.scaleBar(0.001, 120).label, '10 cm');
  for (const mpp of [0.003, 0.7, 3, 41, 900]) {
    const bar = L.scaleBar(mpp, 120);
    assert.ok(bar.pixels <= 120 && bar.pixels > 120 / 5 - 1e-9, `bar fits and is not tiny at ${mpp} m/px: ${bar.pixels}`);
    assert.ok([1, 2, 5].includes(Number((bar.meters / 10 ** Math.floor(Math.log10(bar.meters))).toPrecision(3))));
  }
  const view = L.fitView([{ east: 0, north: 0 }, { east: 100, north: 50 }], { width: 600, height: 300 });
  const a = L.toScreen(view, { width: 600, height: 300 }, { east: 0, north: 0 });
  const b = L.toScreen(view, { width: 600, height: 300 }, { east: 100, north: 50 });
  for (const p of [a, b]) assert.ok(p.x >= 0 && p.x <= 600 && p.y >= 0 && p.y <= 300, `fit keeps ${JSON.stringify(p)} visible`);
  assert.ok(b.y < a.y && b.x > a.x, 'north is up, east is right');
  console.log('  ok scale bar at three zoom levels, fit and screen orientation');
}

function trackSources(L) {
  const sample = (ts, data) => ({ ts, data });
  assert.equal(L.buildTrack([], []), undefined, 'neither position: empty state');
  assert.equal(L.buildTrack([], [sample(1, { lat: 0, lon: 0 })]), undefined, '0/0 is no fix');
  assert.match(L.NO_POSITION_TEXT, /LOCAL_POSITION_NED/);
  assert.match(L.NO_POSITION_TEXT, /GLOBAL_POSITION_INT/);
  const local = L.buildTrack([sample(1, { x: 10, y: -5, z: -2 })], [sample(1, { lat: 10.5, lon: 106.6 })]);
  assert.equal(local.source, 'local');
  assert.deepEqual(local.points[0], { ts: 1, east: -5, north: 10 }, 'NED x is north, y is east');
  const global = L.buildTrack([], [sample(1, { lat: 0, lon: 0 }), sample(2, { lat: 10.5, lon: 106.6 }),
    sample(3, { lat: 10.5 + 100 / 110574, lon: 106.6 })]);
  assert.equal(global.source, 'global');
  assert.deepEqual(global.home, { lat: 10.5, lon: 106.6 }, 'home is the first real fix');
  assert.equal(global.points.length, 2);
  assert.ok(Math.abs(global.points[1].north - 100) < 0.5, `100 m north: ${global.points[1].north}`);
  assert.match(L.trackSummary(global), /first fix \(10\.5000000, 106\.6000000\)/);
  assert.match(L.trackSummary(local), /estimator origin/);
  console.log('  ok track uses local NED first, then GPS around the first fix; empty state names both');
}

function historyMirror(L) {
  const h = new L.SessionHistory();
  for (let i = 0; i < 100; i += 1) h.append('attitude', { ts: 1000 + i * 0.02, data: { roll: i } });
  assert.equal(h.get('attitude').length, 20, '50 Hz in, 10 Hz kept');
  h.append('sensors:imu', { ts: 2000, data: {} });
  assert.deepEqual(h.keys(), ['attitude'], 'only plotted keys are kept');
  h.append('named_value:ADS_A0', { ts: 1000, data: { value: 1 } });
  assert.deepEqual(h.keys('named_value:'), ['named_value:ADS_A0']);
  h.clear(false);
  for (let i = 0; i < L.HISTORY_CAPACITY + 500; i += 1) h.append('vfr', { ts: i / 10, data: { climb: i } });
  const vfr = h.get('vfr');
  assert.equal(vfr.length, L.HISTORY_CAPACITY, 'capped at 10 minutes');
  assert.equal(vfr[vfr.length - 1].data.climb, L.HISTORY_CAPACITY + 499, 'newest kept');
  assert.equal(h.since('vfr', (L.HISTORY_CAPACITY + 499) / 10 - 30).length, 301, '30 s window');
  const seeded = new L.SessionHistory();
  seeded.append('battery', { ts: 50, data: { voltage: 12 } });
  seeded.seed({ battery: [{ ts: 10, data: { voltage: 11 } }, { ts: 20, data: { voltage: 11.5 } }], 'sensors:baro': [] });
  assert.deepEqual(seeded.get('battery').map((s) => s.ts), [10, 20, 50], 'local samples after the host history stay');
  assert.ok(seeded.seeded);
  assert.equal(seeded.latestTs(), 50);

  const state = new L.WebviewState(() => 0);
  state.apply({ type: 'values', stale: false, values: { position: { ts: 1, data: { lat: 1, lon: 1 } } } });
  state.apply({ type: 'values', stale: false, values: { position: { ts: 2, data: { lat: 1, lon: 1 } } } });
  assert.equal(state.history.get('position').length, 2, 'live values feed the history');
  state.apply({ type: 'connection', connection: 'connecting', link: null, stale: false });
  assert.equal(state.history.get('position').length, 0, 'a new connection starts an empty history');
  assert.ok(state.history.seeded, 'nothing to fetch for a new connection');
  console.log('  ok history mirror: 10 Hz decimation, 10-minute cap, seeding, reset on connect');
}

function plotWindows(L) {
  assert.deepEqual([...L.PLOT_WINDOWS], [30, 120, 600]);
  const samples = [];
  for (let i = 0; i <= 6000; i += 1) samples.push({ ts: 100 + i / 10, data: { roll: (i % 2 ? 1 : -1) * Math.PI / 2 } });
  const roll = L.FIXED_SERIES.find((s) => s.id === 'roll');
  for (const seconds of L.PLOT_WINDOWS) {
    const [xs, ys] = L.windowData(samples, roll, 700, seconds);
    assert.equal(xs.length, seconds * 10 + 1, `${seconds} s window has ${seconds * 10 + 1} samples`);
    assert.ok(xs[0] >= 700 - seconds && xs[xs.length - 1] <= 700);
    assert.ok(Math.abs(Math.abs(ys[0]) - 90) < 1e-9, 'roll in degrees');
  }
  const [, gaps] = L.windowData([{ ts: 1, data: { roll: 'x' } }], roll, 1, 30);
  assert.deepEqual(gaps, [null], 'non-numbers are gaps');
  const names = Array.from({ length: 70 }, (_, i) => `named_value:N${String(i).padStart(2, '0')}`);
  const catalog = L.seriesCatalog([...names, 'attitude']);
  assert.equal(catalog.length, L.FIXED_SERIES.length + 64, 'named values capped at 64');
  assert.equal(catalog[L.FIXED_SERIES.length].label, 'N00');
  for (const id of ['roll', 'pitch', 'yaw', 'altitude', 'climb', 'groundspeed', 'voltage', 'current']) {
    assert.ok(L.FIXED_SERIES.some((s) => s.id === id), `catalog has ${id}`);
  }
  console.log('  ok plot windows (30 s, 2 min, 10 min), gaps and the 64 named-value cap');
}

async function hostHistory(L) {
  const port = await freeUdpPort();
  const peer = new Peer({ udpTarget: `127.0.0.1:${port}`, config: { circle: { radius: 40, period: 4 } } });
  await peer.ready;
  const store = new L.VehicleStateStore();
  const controller = new L.ConnectionController({ pythonDir: PYTHON_DIR, store, log: () => {} });
  const posted = [];
  const router = new L.DashboardRouter({
    controller, store, journal: new L.SessionJournal(), confirm: async () => false, confirmAction: async () => false,
    logHost: { pickDestination: async () => undefined, freeBytes: async () => undefined, finished() {} },
    recording: () => ({ active: false }),
    controlEnabled: () => true, runCommand: () => {}, copy: () => {}, log: () => {},
  });
  router.attach((m) => posted.push(m));
  try {
    await controller.connect(PYTHON, async () => ({ transport: 'udp', host: '127.0.0.1', port, controlEnabled: true,
      sessionId: 't' }));
    await waitFor(() => store.series('local_position').length >= 15, 8000, 'local position history');
    await router.handle({ type: 'history_request' });
    const reply = posted.filter((m) => m.type === 'history').at(-1);
    assert.ok(reply, 'history reply');
    const keys = Object.keys(reply.series);
    for (const key of ['attitude', 'position', 'local_position', 'battery', 'vfr', 'named_value:ADS_A0']) {
      assert.ok(keys.includes(key), `history has ${key}`);
    }
    assert.ok(!keys.some((k) => k.startsWith('sensors:')), 'sensor history is not sent');
    const track = L.buildTrack(reply.series.local_position, reply.series.position);
    assert.equal(track.source, 'local');
    const radii = track.points.map((p) => Math.hypot(p.east, p.north));
    assert.ok(radii.every((r) => Math.abs(r - 40) < 0.5), `circle radius 40 m: ${radii.slice(0, 3)}`);
    const bearings = new Set(track.points.map((p) => Math.floor(L.distanceBearing({ east: 0, north: 0 }, p).bearing / 90)));
    assert.ok(bearings.size >= 2, 'the vehicle moves round the circle');
    const global = L.buildTrack([], reply.series.position);
    const gRadii = global.points.map((p) => Math.hypot(p.east - global.points[0].east, p.north - global.points[0].north));
    assert.ok(Math.max(...gRadii) > 20 && Math.max(...gRadii) <= 80.5, `GPS track spans the circle: ${Math.max(...gRadii)}`);
    console.log(`  ok host history over the sidecar: ${track.points.length} circle points, local and GPS tracks agree`);
  } finally {
    router.dispose();
    await controller.dispose();
    store.dispose();
    await peer.stop();
  }
}

/** Lines of a source file with comments removed (block and line comments, outside strings). */
function codeWithoutComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').split('\n').map((line) => line.replace(/(^|[^:'"`])\/\/.*$/, '$1'));
}

function noTilesOrRemoteOrigins(extDir) {
  const root = path.join(extDir, 'src', 'webview');
  const files = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith('.ts')) files.push(full);
    }
  };
  walk(root);
  const hits = [];
  for (const file of files) {
    codeWithoutComments(fs.readFileSync(file, 'utf8')).forEach((line, i) => {
      // The SVG namespace is an identifier, not a fetch; everything else is a remote origin.
      if (/https?:\/\//.test(line.replace('http://www.w3.org/2000/svg', ''))) hits.push(`${path.relative(extDir, file)}:${i + 1}`);
    });
  }
  assert.deepEqual(hits, [], `remote origins in webview code: ${hits.join(', ')}`);
  const pkg = JSON.parse(fs.readFileSync(path.join(extDir, 'package.json'), 'utf8'));
  const deps = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies });
  const mapLibs = deps.filter((d) => /leaflet|maplibre|mapbox|openlayers|^ol$|cesium|tile|deck\.gl/i.test(d));
  assert.deepEqual(mapLibs, [], 'no map or tile library');
  assert.equal(pkg.devDependencies.uplot, '1.6.31', 'uPlot is pinned exactly');
  console.log(`  ok no remote origins in ${files.length} webview files, no map or tile library`);
}

async function run({ EXT_DIR }) {
  const L = buildLogic(EXT_DIR);
  projection(L);
  distanceAndBearing(L);
  scaleBars(L);
  trackSources(L);
  historyMirror(L);
  plotWindows(L);
  noTilesOrRemoteOrigins(EXT_DIR);
  await hostHistory(L);
}

module.exports = { run };
