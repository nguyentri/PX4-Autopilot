// Serial lease interop with the firmware workspace on a pseudo-terminal, using
// a private FIRMWARE_WORKSPACE_RUNTIME folder: the listen-only probe, PORT_BUSY
// in both directions, and the same lock path and metadata keys as
// Tools/firmware_workspace/serial_console.py.
const assert = require('assert');
const { spawn, spawnSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { Bridge, Peer, PYTHON, killAll, tempDir, track, waitFor } = require('./bridge-test-harness');

function leaseFiles(runtime) {
  const dir = path.join(runtime, 'uart');
  const names = fs.existsSync(dir) ? fs.readdirSync(dir) : [];
  const json = names.filter((n) => n.endsWith('.json'));
  return { dir, locks: names.filter((n) => n.endsWith('.lock')), json };
}

function readMetadata(runtime) {
  const { dir, json } = leaseFiles(runtime);
  return json.length === 1 ? JSON.parse(fs.readFileSync(path.join(dir, json[0]), 'utf8')) : null;
}

async function firmwareHoldsPort(ctx, env) {
  const peer = new Peer({ pty: true, config: { heartbeatOnly: true } });
  const { pty } = await peer.ready;
  const sessionId = crypto.randomUUID();
  const tcpPort = 20000 + Math.floor(Math.random() * 20000);
  const relay = track(spawn(PYTHON, ['-m', 'firmware_workspace.serial_console', '--device', pty, '--baud', '115200',
    '--session-id', sessionId, '--tcp', String(tcpPort)], { cwd: ctx.toolsDir, env, stdio: 'ignore' }));
  const metadata = await waitFor(() => readMetadata(env.FIRMWARE_WORKSPACE_RUNTIME), 5000, 'firmware lease metadata');
  const bridge = new Bridge(env);
  const error = await bridge.fail('connect', { transport: 'serial', device: pty, probeSeconds: 1 }, 'PORT_BUSY');
  assert.deepEqual(error.details.owner, { kind: 'firmware-workspace', sessionId, pid: relay.pid, device: metadata.device, tcpPort });
  assert.equal(peer.log().filter((e) => e.kind === 'rx_bytes').length, 0, 'nothing written while refused');
  relay.kill('SIGTERM');
  await relay.exited;
  await bridge.close();
  await peer.stop();
  console.log('  ok serial_console.py --tcp holds the port: the sidecar returns PORT_BUSY naming its session');
  return metadata;
}

async function sidecarHoldsPort(ctx, env, firmwareMetadata) {
  const peer = new Peer({ pty: true, config: { startDelay: 1.5 } });
  const { pty } = await peer.ready;
  const sessionId = crypto.randomUUID();
  const bridge = new Bridge(env);
  const reply = await bridge.ok('connect', { transport: 'serial', device: pty, sessionId,
    baudCandidates: [57600, 115200], probeSeconds: 3 }, 20000);
  assert.deepEqual([reply.transport, reply.baud, reply.systemId], ['serial', 57600, 1], 'probe result reported');
  const log = await waitFor(() => {
    const entries = peer.log();
    return entries.some((e) => e.kind === 'rx_bytes') ? entries : null;
  }, 3000, 'the shell close reaching the peer');
  const firstTx = log.find((e) => e.kind === 'first_tx');
  const firstRx = log.find((e) => e.kind === 'rx_bytes');
  assert.ok(firstTx, 'peer sent a heartbeat');
  assert.ok(log.indexOf(firstRx) > log.indexOf(firstTx), 'the probe wrote nothing before the first heartbeat');

  const runtime = env.FIRMWARE_WORKSPACE_RUNTIME;
  const metadata = readMetadata(runtime);
  assert.equal(metadata.sessionId, sessionId);
  assert.deepEqual(Object.keys(metadata).sort(), Object.keys(firmwareMetadata).sort(), 'metadata keys match the firmware workspace');
  assert.deepEqual(leaseFiles(runtime).locks.sort(), [...new Set([`${firmwareMetadata.identity}.lock`, `${metadata.identity}.lock`])].sort(),
    'lock files use the same <major>-<minor>.lock path');

  const check = spawnSync(PYTHON, ['-m', 'firmware_workspace.serial_console', '--device', pty, '--baud', '115200',
    '--session-id', crypto.randomUUID(), '--check'], { cwd: ctx.toolsDir, env, encoding: 'utf8' });
  assert.equal(check.status, 4, `serial_console.py --check while the sidecar holds the port\n${check.stderr}`);
  assert.match(check.stderr, /UART_BUSY/);

  const second = new Bridge(env);
  const busy = await second.fail('connect', { transport: 'serial', device: pty, probeSeconds: 1 }, 'PORT_BUSY');
  assert.deepEqual([busy.details.owner.kind, busy.details.owner.sessionId], ['gcs', sessionId]);
  await second.close();
  console.log('  ok listen-only probe, sidecar lease refuses serial_console.py and a second sidecar, same lock path and keys');

  await bridge.ok('disconnect');
  assert.equal(readMetadata(runtime), null, 'metadata removed on disconnect');
  const free = spawnSync(PYTHON, ['-m', 'firmware_workspace.serial_console', '--device', pty, '--baud', '115200',
    '--session-id', crypto.randomUUID(), '--check'], { cwd: ctx.toolsDir, env, encoding: 'utf8' });
  assert.equal(free.status, 0, `the port is free after disconnect\n${free.stderr}`);
  await bridge.close();
  await peer.stop();
  console.log('  ok disconnect releases the lease');
}

async function run({ REPO_ROOT }) {
  const toolsDir = path.join(REPO_ROOT, 'Tools');
  if (process.platform !== 'linux') {
    console.log('  SKIP serial lease tests: the lease is Linux only');
    return;
  }
  if (!fs.existsSync(path.join(toolsDir, 'firmware_workspace', 'serial_console.py'))) {
    console.log('  SKIP serial lease tests: the repository firmware workspace backend is absent');
    return;
  }
  const env = { ...process.env, FIRMWARE_WORKSPACE_RUNTIME: path.join(tempDir('px4-gcs-lease-'), 'runtime') };
  try {
    const firmwareMetadata = await firmwareHoldsPort({ toolsDir }, env);
    await sidecarHoldsPort({ toolsDir }, env, firmwareMetadata);
  } finally {
    await killAll();
  }
}

module.exports = { run };
