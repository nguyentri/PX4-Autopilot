// The dashboard router against the real sidecar and vehicle peer: the NSH
// console warning, journal and control gate, and stream demand that raises a
// rate once for several owners and restores it exactly.
const assert = require('assert');
const path = require('path');
const { Peer, PYTHON, PYTHON_DIR, freeUdpPort, sleep, tempDir, waitFor } = require('./bridge-test-harness');

function buildInternals(extDir) {
  const out = path.join(tempDir('px4-gcs-router-'), 'router.js');
  require('esbuild').buildSync({
    stdin: {
      contents: [
        "export * from './src/connection/connection-controller';", "export * from './src/vehicle/vehicle-state-store';",
        "export * from './src/session/session-journal';", "export * from './src/dashboard/dashboard-router';",
        "export * from './src/console/console-session';",
      ].join('\n'),
      resolveDir: extDir, loader: 'ts',
    },
    bundle: true, platform: 'node', format: 'cjs', target: 'node18', outfile: out, logLevel: 'silent',
  });
  return require(out);
}

/** A router wired to a real controller; `answers` scripts the console modal. */
async function setup(I, peerConfig = {}) {
  const port = await freeUdpPort();
  const peer = new Peer({ udpTarget: `127.0.0.1:${port}`, config: peerConfig });
  await peer.ready;
  const store = new I.VehicleStateStore();
  const controller = new I.ConnectionController({ pythonDir: PYTHON_DIR, store, log: () => {} });
  const journal = new I.SessionJournal();
  const ctx = { peer, store, controller, journal, answers: [], confirms: [], control: true, posted: [] };
  ctx.router = new I.DashboardRouter({
    controller, store, journal,
    confirm: async (message) => { ctx.confirms.push(message); return ctx.answers.shift() === true; },
    controlEnabled: () => ctx.control,
    logHost: { pickDestination: async () => undefined, freeBytes: async () => undefined, finished() {} },
    recording: () => ({ active: false }),
    runCommand: () => {}, copy: () => {}, log: () => {},
  });
  ctx.router.attach((message) => ctx.posted.push(message));
  ctx.connect = () => controller.connect(PYTHON, async () => ({
    transport: 'udp', host: '127.0.0.1', port, controlEnabled: true, sessionId: 't',
  }));
  // Frames that open the shell or carry input; the sidecar's close-on-connect frame (flags 0) is not one.
  ctx.shellFrames = () => peer.log().filter((e) => e.kind === 'shell' && e.flags !== 0);
  ctx.stop = async () => {
    ctx.router.dispose();
    await controller.dispose();
    store.dispose();
    await peer.stop();
  };
  await ctx.connect();
  await ctx.router.setVisible(true);
  return ctx;
}

async function consoleWarningAndJournal(I) {
  const ctx = await setup(I);
  const { router, journal } = ctx;
  await router.selectTab('console');

  ctx.answers.push(false);
  await router.handle({ type: 'console_open' });
  assert.equal(router.console.state.state, 'declined');
  assert.equal(ctx.confirms.length, 1, 'the warning was shown');
  assert.match(ctx.confirms[0], /skip the confirmations/);
  assert.equal(journal.entries('console_declined').length, 1);
  await router.handle({ type: 'console_input', data: 'ver all\r' });
  await sleep(300);
  assert.equal(ctx.shellFrames().length, 0, 'a declined console sends no SERIAL_CONTROL');

  ctx.answers.push(true);
  await router.handle({ type: 'console_open' });
  assert.equal(router.console.state.state, 'open');
  assert.equal(journal.entries('console_opened').length, 1);
  await router.handle({ type: 'console_input', data: 'ver all\r' });
  await router.handle({ type: 'console_input', data: 'lx\x7fs\r' });
  await router.handle({ type: 'console_input', data: '\x1b[A\r' });
  const lines = journal.entries('console_line').map((e) => e.data.line);
  assert.deepEqual(lines, ['ver all', 'ls', '<ESC>[A'], 'each line journaled once, after editing');
  await waitFor(() => ctx.posted.some((m) => m.type === 'shell' && m.text.includes('nsh> ')), 5000, 'shell echo');
  assert.ok(ctx.shellFrames().some((f) => f.count > 0), 'typed bytes reached the vehicle');

  await router.selectTab('fly');
  assert.equal(router.console.state.state, 'closed', 'leaving the tab closes the shell');
  await router.selectTab('console');
  await router.handle({ type: 'console_open' });
  assert.equal(ctx.confirms.length, 2, 'reopening on the same connection does not ask again');
  assert.equal(router.console.state.state, 'open');

  await ctx.controller.disconnect();
  assert.equal(router.console.state.state, 'closed');
  await ctx.connect();
  ctx.answers.push(true);
  await router.handle({ type: 'console_open' });
  assert.equal(ctx.confirms.length, 3, 'a new connection asks again');
  assert.equal(router.console.state.state, 'open');

  ctx.control = false;
  await sleep(300); // let the open frame of the previous step reach the peer log
  const before = ctx.shellFrames().length;
  assert.equal(await router.console.write('reboot\r'), false, 'control disabled blocks input');
  await router.console.close();
  await router.handle({ type: 'console_open' });
  assert.equal(router.console.state.state, 'disabled');
  assert.match(router.console.state.reason, /px4Gcs\.control\.enabled/);
  await sleep(300);
  assert.equal(ctx.shellFrames().length, before, 'nothing typed or opened after control was disabled');
  assert.ok(!journal.entries('console_line').some((e) => e.data.line === 'reboot'));
  await ctx.stop();
  console.log('  ok console: warning per connection, decline sends nothing, lines journaled, control gate');
}

async function streamDemandRestores(I) {
  const ctx = await setup(I);
  const { router, peer } = ctx;
  const sets = (id) => peer.log().filter((e) => e.kind === 'interval_set' && e.message === id);

  await router.selectTab('sensors');
  await waitFor(() => sets(105).length === 1, 5000, 'HIGHRES_IMU raised');
  assert.equal(sets(105)[0].interval, 100000);
  await waitFor(() => ctx.posted.some((m) => m.type === 'stream_note' && m.message === 29 && m.outcome === 'refused'),
    5000, 'SCALED_PRESSURE refusal note');
  assert.equal(sets(29).length, 0, 'a message without a current stream is left alone');

  await router.streams.acquire('plots', [{ message: 105, intervalUs: 100000 }]);
  assert.equal(router.streams.refCount(105), 2);
  await router.selectTab('fly');
  await sleep(300);
  assert.equal(sets(105).length, 1, 'still held by the second owner: no restore yet');
  await router.streams.releaseOwner('plots');
  await waitFor(() => sets(105).length === 2, 5000, 'restore after the last owner');
  assert.equal(sets(105)[1].interval, 20000, 'restored to the exact original interval');

  await router.selectTab('sensors');
  await waitFor(() => sets(105).length === 3, 5000, 'raised again');
  await ctx.controller.disconnect();
  await waitFor(() => sets(105).length === 4, 5000, 'restored on disconnect');
  assert.equal(sets(105)[3].interval, 20000);
  assert.equal(router.streams.refCount(105), 0, 'demand forgotten after disconnect');
  await ctx.stop();
  console.log('  ok stream demand: one raise for two owners, exact restore on release and disconnect');
}

async function run({ EXT_DIR }) {
  const I = buildInternals(EXT_DIR);
  await consoleWarningAndJournal(I);
  await streamDemandRestores(I);
}

module.exports = { run };
