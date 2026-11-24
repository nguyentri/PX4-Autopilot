// Host-side log and session services against the real sidecar and peer: the
// three log-list outcomes (entries, silent while heartbeats continue, link
// lost), the free-space refusal before any LOG_REQUEST_DATA, the busy guard,
// the recorder (no file without a start, file name, stop, disconnect), and the
// HTML report (vehicle text escaped, no script, no remote resource).
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { Peer, PYTHON, PYTHON_DIR, freeUdpPort, sleep, tempDir, waitFor } = require('./bridge-test-harness');

function buildInternals(extDir) {
  const out = path.join(tempDir('px4-gcs-logs-host-'), 'logs.js');
  require('esbuild').buildSync({
    stdin: {
      contents: [
        "export * from './src/connection/connection-controller';", "export * from './src/vehicle/vehicle-state-store';",
        "export * from './src/session/session-journal';", "export * from './src/logs/log-list-store';",
        "export * from './src/logs/log-download-service';", "export * from './src/logs/log-transfer-format';",
        "export * from './src/session/session-recorder';", "export * from './src/session/session-journal-feed';",
        "export * from './src/session/session-report-builder';", "export * from './src/session/html-escape';",
        "export { NO_LOGS_TEXT } from './src/dashboard/dashboard-messages';",
      ].join('\n'),
      resolveDir: extDir, loader: 'ts',
    },
    bundle: true, platform: 'node', format: 'cjs', target: 'node18', outfile: out, logLevel: 'silent',
  });
  return require(out);
}

async function connect(I, peerConfig = {}) {
  const port = await freeUdpPort();
  const peer = new Peer({ udpTarget: `127.0.0.1:${port}`, config: peerConfig });
  await peer.ready;
  const store = new I.VehicleStateStore();
  const controller = new I.ConnectionController({ pythonDir: PYTHON_DIR, store, log: () => {} });
  const journal = new I.SessionJournal();
  await controller.connect(PYTHON, async () => ({ transport: 'udp', host: '127.0.0.1', port, controlEnabled: true,
    sessionId: 't' }));
  await waitFor(() => store.get('heartbeat') !== undefined, 5000, 'first heartbeat');
  const stop = async () => {
    await controller.dispose();
    store.dispose();
    await peer.stop();
  };
  return { peer, store, controller, journal, stop };
}

async function logListOutcomes(I) {
  let ctx = await connect(I);
  const states = [];
  let logs = new I.LogListStore(ctx.controller, (s) => states.push(s.state));
  await logs.load();
  assert.equal(logs.state.state, 'done');
  assert.deepEqual(logs.state.entries.map((e) => e.id), [1, 2]);
  assert.deepEqual(states, ['loading', 'done']);
  assert.equal(logs.entry(2).size, 2048);
  logs.dispose();
  await ctx.stop();

  ctx = await connect(I, { logListSilent: true });
  logs = new I.LogListStore(ctx.controller, () => {});
  await logs.load();
  assert.equal(logs.state.state, 'done', 'silence with heartbeats is not an error');
  assert.equal(logs.state.answered, false);
  assert.equal(logs.state.entries.length, 0);
  assert.equal(ctx.controller.state, 'connected');
  assert.match(I.NO_LOGS_TEXT, /reported no logs/);

  ctx.peer.child.kill('SIGUSR1'); // mute: no frames, the watchdog reports lost
  await waitFor(() => ctx.controller.state === 'lost', 6000, 'link lost');
  await logs.load();
  assert.equal(logs.state.state, 'error');
  assert.match(logs.state.message, /link to the vehicle is lost/i, 'a lost link is not "no logs"');
  logs.dispose();
  await ctx.stop();

  // The link drops while the request waits: the silent reply must still read as the lost link.
  const fake = { state: 'connected', onDidChangeState: () => ({ dispose() {} }),
    client: { request: async () => { fake.state = 'lost'; return { entries: [], answered: false }; } } };
  logs = new I.LogListStore(fake, () => {});
  await logs.load();
  assert.equal(logs.state.state, 'error');
  assert.match(logs.state.message, /lost/);
  console.log('  ok log list: entries; silent + heartbeats = "no logs"; lost link = error, also mid-request');
}

async function downloadGuards(I) {
  const ctx = await connect(I, { log: { size: 60000, seed: 5 } });
  const dir = tempDir('px4-gcs-dl-');
  const dest = path.join(dir, 'log-1.ulg');
  const finished = [];
  const transfers = [];
  let free = 1000;
  let gate;
  const service = new I.LogDownloadService({
    controller: ctx.controller, journal: ctx.journal, onTransfer: (t) => transfers.push(t),
    host: {
      pickDestination: async () => { if (gate) await gate; return dest; },
      freeBytes: async () => free,
      finished: (t) => finished.push(t),
    },
  });
  const entry = { id: 1, size: 60000, timeUtc: null };

  let result = await service.download(entry);
  assert.equal(result.state, 'refused');
  assert.match(result.message, /60000 bytes .* 1000 bytes/, 'refusal names both byte counts');
  await sleep(300);
  assert.equal(ctx.peer.received('LOG_REQUEST_DATA').length, 0, 'nothing requested from the vehicle');
  assert.equal(fs.existsSync(dest), false);
  assert.equal(ctx.journal.entries('log_download').at(-1).data.result, 'refused');

  // A second request while the first is still in its save dialog is refused.
  let open;
  gate = new Promise((resolve) => { open = resolve; });
  free = undefined;
  const first = service.download(entry);
  const second = await service.download(entry);
  assert.equal(second.state, 'refused');
  assert.match(second.message, /Another log download/);
  open();
  gate = undefined;
  result = await first;
  assert.equal(result.state, 'done', JSON.stringify(result));
  assert.match(result.message, /Free space could not be read; downloading anyway/);
  assert.equal(fs.statSync(dest).size, 60000);
  assert.ok(transfers.some((t) => t && t.state === 'running'), 'running state was shown');
  assert.equal(I.transferText({ received: 30720, total: 61440, rateBps: 2048 }), '30.0 kB of 60.0 kB (50 %), 2.0 kB/s');
  assert.deepEqual(finished.map((t) => t.state), ['refused', 'refused', 'done']);
  const done = ctx.journal.entries('log_download').at(-1).data;
  assert.equal(done.result, 'done');
  assert.ok(typeof done.sha256 === 'string' && done.sha256.length === 64);
  await ctx.stop();
  console.log('  ok download: free-space refusal before any LOG_REQUEST_DATA, busy guard, unknown free space noted');
}

async function recorder(I) {
  const ctx = await connect(I);
  const dir = path.join(tempDir('px4-gcs-rec-host-'), 'sessions');
  const states = [];
  let clock = new Date('2026-11-18T10:15:02.345Z');
  const feed = new I.SessionJournalFeed(ctx.controller, ctx.journal);
  const rec = new I.SessionRecorder({ controller: ctx.controller, journal: ctx.journal, directory: () => dir,
    onState: (s) => states.push(s), now: () => clock });
  assert.equal(I.recordingFileName(new Date('2026-11-18T10:15:02.345Z')), 'px4-gcs-20261118T101502Z.tlog');
  await sleep(400);
  assert.equal(fs.existsSync(dir), false, 'no folder and no file without an explicit start');
  assert.equal(await rec.stop(), undefined);

  const file = await rec.start();
  assert.equal(file, path.join(dir, 'px4-gcs-20261118T101502Z.tlog'));
  await assert.rejects(rec.start(), /Already recording/);
  await sleep(600);
  assert.equal(await rec.stop(), file);
  assert.equal(rec.state.active, false);
  assert.ok(fs.statSync(file).size > 0);

  clock = new Date('2026-11-18T10:16:00Z');
  const second = await rec.start();
  assert.notEqual(second, file);
  await ctx.controller.disconnect();
  await waitFor(() => !rec.state.active, 3000, 'recording ends on disconnect');
  assert.equal(rec.state.reason, 'disconnect');
  const recordings = ctx.journal.entries('recording').map((e) => [e.data.state, e.data.reason ?? null]);
  assert.deepEqual(recordings.slice(0, 2), [['started', null], ['stopped', 'operator']]);
  assert.deepEqual(recordings.at(-1), ['stopped', 'disconnect']);
  await assert.rejects(rec.start(), /Connect to a vehicle/);
  assert.deepEqual(states.map((r) => r.active), [true, false, true, false], 'tree, status bar and page see each change');
  rec.dispose();
  feed.dispose();
  await ctx.stop();
  console.log('  ok recorder: nothing without start, UTC file name, stop journaled, disconnect ends it');
}

function report(I) {
  const journal = new I.SessionJournal();
  const evil = '<script>alert(1)</script>';
  journal.append('connection', { state: 'connected', systemId: 1, transport: 'serial', port: '/dev/ttyUSB0',
    baud: 57600, host: null, udpPort: null });
  journal.append('statustext', { severity: 4, text: `${evil} "q" & 'a'`, partial: false });
  journal.append('console_opened', { systemId: 1 });
  journal.append('console_line', { line: `nsh> ${evil}<img src=x onerror=alert(2)>` });
  journal.append('param_write', { name: 'MPC_<b>', old: 1, requested: 2, now: 2, result: 'accepted' });
  journal.append('recording', { state: 'started', path: `/tmp/${evil}.tlog` });
  const feed = new I.SessionJournalFeed({ onDidChangeState: () => ({ dispose() {} }), onEvent: () => ({ dispose() {} }) },
    journal);
  feed.statistics.add('local_position', { x: 0, y: 0 }, '2026-11-18T10:00:00.000Z');
  feed.statistics.add('local_position', { x: 10, y: 5 }, '2026-11-18T10:00:01.000Z');
  feed.statistics.add('position', { relativeAlt: 12.5 }, '2026-11-18T10:00:01.000Z');
  const html = I.buildSessionReport({ journal, statistics: feed.statistics, started: '2026-11-18T10:00:00.000Z',
    generated: new Date('2026-11-18T10:05:30Z'), extensionVersion: '0.1.0' });
  assert.ok(!/<script/i.test(html), 'no script element');
  assert.ok(!/https?:\/\//i.test(html), 'no remote resource');
  assert.ok(!/<img/i.test(html) && !/<b>/.test(html), 'vehicle text never becomes markup');
  assert.ok(html.includes('&lt;script&gt;alert(1)&lt;/script&gt;'), 'statustext escaped');
  assert.ok(html.includes('&quot;q&quot; &amp; &#39;a&#39;'), 'quotes and ampersand escaped');
  assert.ok(html.includes("default-src 'none'"), 'CSP forbids everything but inline style');
  assert.ok(html.includes('serial /dev/ttyUSB0 @ 57600') && html.includes('system 1'), 'vehicle and link in the summary');
  assert.ok(html.includes('5 min 30 s'), 'session length');
  assert.ok(html.includes('12.5 m'), 'highest altitude');
  assert.ok(/<polyline/.test(html), 'track drawn');
  assert.equal(I.escapeHtml('a\u0000b\u001bc'), 'abc', 'control characters dropped');
  feed.dispose();
  console.log('  ok report: statustext, console, parameter and path text escaped; no script, no http; summary rows');
}

async function run(ctx) {
  const I = buildInternals(ctx.EXT_DIR);
  report(I);
  await logListOutcomes(I);
  await downloadGuards(I);
  await recorder(I);
}

module.exports = { run };
