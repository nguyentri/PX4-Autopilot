// Host-side connection tests: the bundled extension with `vscode` stubbed,
// the real sidecar and the vehicle peer. Internals (spawn plan, client,
// controller) come from a test bundle built from src/ into a temp folder.
const assert = require('assert');
const { spawnSync } = require('child_process');
const dgram = require('dgram');
const fs = require('fs');
const path = require('path');
const { Bridge, Peer, PYTHON, PYTHON_DIR, freeUdpPort, killAll, sleep, tempDir, waitFor } = require('./bridge-test-harness');
const { createVscodeStub, loadExtension } = require('./vscode-stub');

const SCHEMA = path.resolve(__dirname, '..', 'schemas', 'bridge-protocol.schema.json');

function buildInternals(extDir) {
  const out = path.join(tempDir('px4-gcs-internals-'), 'internals.js');
  require('esbuild').buildSync({
    stdin: {
      contents: [
        "export * from './src/bridge/bridge-protocol';", "export * from './src/bridge/bridge-process';",
        "export * from './src/bridge/bridge-client';", "export * from './src/connection/connection-controller';",
        "export * from './src/vehicle/vehicle-state-store';",
      ].join('\n'),
      resolveDir: extDir, loader: 'ts',
    },
    bundle: true, platform: 'node', format: 'cjs', target: 'node18', outfile: out, logLevel: 'silent',
  });
  return require(out);
}

/** Sidecar processes that are children of this test process. */
function sidecarChildren() {
  const ps = spawnSync('ps', ['-o', 'pid=,args=', '--ppid', String(process.pid)], { encoding: 'utf8' });
  return ps.stdout.split('\n').filter((l) => l.includes('px4_gcs_bridge')).map((l) => Number(l.trim().split(/\s+/)[0]));
}

function alive(pid) {
  try { process.kill(pid, 0); return true; } catch { return false; }
}

function startExtension(extDir, options) {
  const stub = createVscodeStub({ extensionPath: extDir, ...options, config: { 'px4Gcs.pythonPath': PYTHON, ...options.config } });
  const ext = loadExtension(extDir, stub);
  const api = ext.activate(stub.context);
  const tree = () => {
    const provider = stub.vscode.__trees.get('px4Gcs.vehicle');
    return provider.getChildren().map((row) => provider.getTreeItem(row));
  };
  const stop = async () => {
    await ext.deactivate();
    for (const d of stub.context.subscriptions) d.dispose();
  };
  return { stub, ext, controller: api.controller, tree, stop };
}

const errors = (stub) => stub.messages.filter((m) => m.kind === 'error');

async function schemaNames(internals) {
  const defs = JSON.parse(fs.readFileSync(SCHEMA, 'utf8')).definitions;
  assert.deepEqual([...internals.COMMAND_NAMES].sort(), [...defs.commandName.enum].sort());
  assert.deepEqual([...internals.ERROR_CODES].sort(), [...defs.errorCode.enum].sort());
  assert.deepEqual([...internals.EVENT_NAMES].sort(), [...defs.event.properties.name.enum].sort());
  console.log('  ok every schema command, event and error code has a TypeScript counterpart');
}

async function udpConnectLostDisconnect(extDir) {
  const port = await freeUdpPort();
  const peer = new Peer({ udpTarget: `127.0.0.1:${port}` });
  await peer.ready;
  const gcs = startExtension(extDir, { config: { 'px4Gcs.transport': 'udp', 'px4Gcs.udp.port': port } });
  await gcs.stub.commands.get('px4Gcs.quickConnect')();
  assert.equal(gcs.controller.state, 'connected', JSON.stringify(gcs.stub.messages));
  const items = await waitFor(() => {
    const rows = gcs.tree();
    return rows.some((r) => r.id === 'battery') && rows.some((r) => r.id === 'armed') ? rows : null;
  }, 5000, 'battery and armed rows');
  const byId = Object.fromEntries(items.map((r) => [r.id, r.description]));
  assert.match(byId.link, /^connected · udp 127\.0\.0\.1:/);
  assert.match(byId.identity, /^system 1 · PX4/);
  assert.equal(byId.mode, 'Position');
  assert.equal(byId.armed, 'disarmed');
  assert.match(byId.battery, /V/);
  console.log(`  ok UDP Quick Connect: tree shows ${items.map((r) => r.id).join(', ')}`);

  peer.child.kill('SIGUSR1');
  await waitFor(() => gcs.controller.state === 'lost', 6000, 'lost state');
  await sleep(100);
  assert.match(gcs.tree().find((r) => r.id === 'mode').description, /\(stale\)$/, 'values greyed while lost');
  peer.child.kill('SIGUSR1');
  await waitFor(() => gcs.controller.state === 'connected', 4000, 'recovered state');
  console.log('  ok link loss keeps values (stale) and recovers on the next heartbeat');

  const pid = gcs.controller.pid;
  await gcs.stub.commands.get('px4Gcs.disconnect')();
  assert.equal(gcs.controller.state, 'idle');
  assert.equal(gcs.tree().length, 0, 'idle tree is empty so the welcome view shows');
  assert.ok(!alive(pid), 'sidecar stopped on disconnect');
  await gcs.stop();
  await peer.stop();
  console.log('  ok Disconnect stops the sidecar and empties the tree');
}

async function portBusy(extDir, runtime) {
  const peer = new Peer({ pty: true, config: { heartbeatOnly: true } });
  const { pty } = await peer.ready;
  const holder = new Bridge({ FIRMWARE_WORKSPACE_RUNTIME: runtime });
  await holder.ok('connect', { transport: 'serial', device: pty, sessionId: 'holder-session-42', baudCandidates: [57600] });
  const gcs = startExtension(extDir, { config: { 'px4Gcs.serial.port': pty } });
  await gcs.stub.commands.get('px4Gcs.quickConnect')();
  const [error] = errors(gcs.stub);
  assert.ok(error, 'PORT_BUSY is reported');
  assert.match(error.message, /in use by another Px4-GCS window \(session holder-session-42, process \d+\)/);
  assert.equal(gcs.controller.state, 'idle');
  assert.equal(gcs.controller.pid, undefined);
  await gcs.stop();
  await holder.close();
  await peer.stop();
  console.log(`  ok PORT_BUSY names the holder: "${error.message}"`);
}

async function sidecarKilled(extDir) {
  const port = await freeUdpPort();
  const peer = new Peer({ udpTarget: `127.0.0.1:${port}` });
  await peer.ready;
  const gcs = startExtension(extDir, { config: { 'px4Gcs.transport': 'udp', 'px4Gcs.udp.port': port } });
  await gcs.stub.commands.get('px4Gcs.quickConnect')();
  assert.equal(gcs.controller.state, 'connected');
  process.kill(gcs.controller.pid, 'SIGKILL');
  await waitFor(() => gcs.controller.state === 'idle', 3000, 'idle after kill');
  const error = await waitFor(() => errors(gcs.stub)[0], 2000, 'exit error');
  assert.match(error.message, /sidecar stopped \(exit code none, signal SIGKILL\)/);
  assert.deepEqual(error.items, ['Run Doctor']);
  await gcs.stop();
  await peer.stop();
  console.log(`  ok sidecar killed mid-session: idle plus "${error.message}"`);
}

async function missingInterpreter(extDir) {
  const gcs = startExtension(extDir, { config: { 'px4Gcs.pythonPath': '/nonexistent/python3', 'px4Gcs.transport': 'udp',
    'px4Gcs.udp.port': await freeUdpPort() } });
  await gcs.stub.commands.get('px4Gcs.quickConnect')();
  await gcs.stub.commands.get('px4Gcs.runDoctor')();
  const found = errors(gcs.stub);
  assert.equal(found.length, 2, JSON.stringify(gcs.stub.messages));
  for (const e of found) {
    assert.match(e.message, /"\/nonexistent\/python3" could not be started \(ENOENT\)/);
    assert.deepEqual(e.items, ['Open Settings', 'Run Doctor']);
  }
  assert.equal(gcs.controller.state, 'idle');
  await gcs.stop();
  console.log('  ok a missing interpreter yields the doctor guidance (connect and doctor)');
}

async function untrusted(extDir) {
  const gcs = startExtension(extDir, { trusted: false, config: { 'px4Gcs.transport': 'udp' } });
  for (const id of ['px4Gcs.quickConnect', 'px4Gcs.connect', 'px4Gcs.runDoctor']) {
    await gcs.stub.commands.get(id)();
  }
  const warnings = gcs.stub.messages.filter((m) => m.kind === 'warning');
  assert.equal(warnings.length, 3);
  for (const w of warnings) {
    assert.match(w.message, /Connecting needs a trusted workspace/);
    assert.deepEqual(w.items, ['Manage Workspace Trust']);
  }
  assert.deepEqual(sidecarChildren(), [], 'no sidecar started');
  await gcs.stop();
  console.log('  ok untrusted workspace: three commands, no process');
}

async function spawnRules(extDir, internals) {
  const hostile = tempDir('px4-gcs-hostile-');
  fs.mkdirSync(path.join(hostile, 'px4_gcs_bridge'));
  fs.writeFileSync(path.join(hostile, 'px4_gcs_bridge', '__init__.py'), '');
  fs.writeFileSync(path.join(hostile, 'px4_gcs_bridge', '__main__.py'), 'print(\'{"hostile": true}\')\n');
  const plan = internals.bridgeSpawnPlan(PYTHON, PYTHON_DIR, [], { PATH: process.env.PATH, PYTHONPATH: `${hostile}:` });
  assert.equal(plan.options.cwd, PYTHON_DIR);
  assert.equal(plan.options.env.PYTHONPATH, PYTHON_DIR);
  assert.equal(plan.options.shell, false);
  assert.deepEqual(plan.args, ['-m', 'px4_gcs_bridge']);

  const saved = process.env.PYTHONPATH;
  process.env.PYTHONPATH = `${hostile}::.`;
  const previousCwd = process.cwd();
  process.chdir(hostile);
  try {
    const gcs = startExtension(extDir, {});
    const report = await gcs.stub.commands.get('px4Gcs.runDoctor')();
    assert.ok(report && report.bridgeVersion === '0.1.0', `real package ran: ${JSON.stringify(report)}`);
    await gcs.stop();
  } finally {
    process.chdir(previousCwd);
    if (saved === undefined) delete process.env.PYTHONPATH; else process.env.PYTHONPATH = saved;
  }
  console.log('  ok spawn rules: packaged folder is cwd and sole PYTHONPATH; a hostile PYTHONPATH and cwd are ignored');
}

async function nonLoopbackDeclined(extDir) {
  const port = await freeUdpPort();
  const gcs = startExtension(extDir, {
    config: { 'px4Gcs.transport': 'udp', 'px4Gcs.udp.host': '0.0.0.0', 'px4Gcs.udp.port': port },
    answers: [undefined],
  });
  await gcs.stub.commands.get('px4Gcs.quickConnect')();
  const [modal] = gcs.stub.messages;
  assert.ok(modal.modal, 'asks with a modal');
  assert.match(modal.message, /Bind UDP 0\.0\.0\.0:\d+\? Any host that can reach this address can send MAVLink/);
  assert.deepEqual(modal.items, ['Bind']);
  assert.deepEqual(sidecarChildren(), [], 'nothing spawned');
  await new Promise((resolve, reject) => {
    const socket = dgram.createSocket('udp4');
    socket.once('error', reject);
    socket.bind(port, '0.0.0.0', () => socket.close(resolve));
  });
  await gcs.stop();
  console.log('  ok non-loopback UDP asks first; declining binds nothing');
}

async function longCommandCancelled(internals) {
  const port = await freeUdpPort();
  const peer = new Peer({ udpTarget: `127.0.0.1:${port}`, config: { paramSilent: true } });
  await peer.ready;
  const store = new internals.VehicleStateStore();
  const controller = new internals.ConnectionController({ pythonDir: PYTHON_DIR, store, log: () => {} });
  await controller.connect(PYTHON, async () => ({ transport: 'udp', host: '127.0.0.1', port, controlEnabled: true, sessionId: 't' }));
  const client = controller.client;
  const cancels = [];
  const realRequest = client.request.bind(client);
  client.request = (cmd, args, options) => {
    const reply = realRequest(cmd, args, options);
    if (cmd === 'cancel') cancels.push(reply);
    return reply;
  };
  const started = Date.now();
  const error = await client.request('param_list').then(() => null, (e) => e);
  const elapsed = Date.now() - started;
  assert.ok(error && error.code === 'TIMEOUT', `param_list rejects with TIMEOUT: ${error}`);
  assert.ok(elapsed >= 4900 && elapsed < 9000, `cancelled after ${elapsed} ms`);
  assert.match(error.message, /no progress for 5 s; cancelled/);
  assert.equal(cancels.length, 1, 'the host sent cancel for the stalled list');
  assert.deepEqual(await cancels[0], { cancelled: true }, 'the sidecar was still running the list and stopped it');
  assert.ok(peer.received('PARAM_REQUEST_LIST').length > 0, 'the list request reached the vehicle');
  const hello = await controller.client.request('hello');
  assert.equal(hello.protocolVersion, 1, 'sidecar still answers after the cancel');
  const pid = controller.pid;
  await controller.dispose();
  store.dispose();
  assert.ok(!alive(pid));
  await peer.stop();
  console.log(`  ok a long command without progress is cancelled after ${elapsed} ms`);
}

async function deactivateStopsChild(extDir) {
  const port = await freeUdpPort();
  const peer = new Peer({ udpTarget: `127.0.0.1:${port}` });
  await peer.ready;
  const gcs = startExtension(extDir, { config: { 'px4Gcs.transport': 'udp', 'px4Gcs.udp.port': port } });
  await gcs.stub.commands.get('px4Gcs.quickConnect')();
  const pid = gcs.controller.pid;
  assert.deepEqual(sidecarChildren(), [pid]);
  await gcs.stop();
  assert.ok(!alive(pid), `sidecar ${pid} gone after deactivate`);
  assert.deepEqual(sidecarChildren(), []);
  await peer.stop();
  console.log(`  ok deactivate leaves no child (sidecar ${pid} gone)`);
}

async function run({ EXT_DIR }) {
  const internals = buildInternals(EXT_DIR);
  const runtime = tempDir('px4-gcs-runtime-');
  const savedRuntime = process.env.FIRMWARE_WORKSPACE_RUNTIME;
  process.env.FIRMWARE_WORKSPACE_RUNTIME = runtime;
  try {
    await schemaNames(internals);
    await udpConnectLostDisconnect(EXT_DIR);
    if (process.platform === 'linux') await portBusy(EXT_DIR, runtime);
    await sidecarKilled(EXT_DIR);
    await missingInterpreter(EXT_DIR);
    await untrusted(EXT_DIR);
    await spawnRules(EXT_DIR, internals);
    await nonLoopbackDeclined(EXT_DIR);
    await longCommandCancelled(internals);
    await deactivateStopsChild(EXT_DIR);
  } finally {
    if (savedRuntime === undefined) delete process.env.FIRMWARE_WORKSPACE_RUNTIME;
    else process.env.FIRMWARE_WORKSPACE_RUNTIME = savedRuntime;
    await killAll();
  }
}

module.exports = { run };
