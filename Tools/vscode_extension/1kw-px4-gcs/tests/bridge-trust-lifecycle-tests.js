// Link trust (foreign senders change nothing and receive nothing) and sidecar
// lifecycle (stdin close, SIGTERM, closed stdout, stalled reader).
const assert = require('assert');
const { Bridge, Peer, freeUdpPort, killAll, sleep } = require('./bridge-test-harness');

async function connected() {
  const port = await freeUdpPort();
  const bridge = new Bridge();
  const peer = new Peer({ udpTarget: `127.0.0.1:${port}` });
  await peer.ready;
  await bridge.ok('connect', { transport: 'udp', port });
  return { port, bridge, peer };
}

async function foreignSenders() {
  const { port, bridge, peer } = await connected();
  const mark = bridge.events.length;
  const armedMode = { heartbeatOnly: false, armed: true, customMode: (4 << 16) | (6 << 24) };
  const otherSystem = new Peer({ udpTarget: `127.0.0.1:${port}`, sysid: 7, config: armedMode });
  const sameSystemOtherAddress = new Peer({ udpTarget: `127.0.0.1:${port}`, sysid: 1, config: armedMode });
  await Promise.all([otherSystem.ready, sameSystemOtherAddress.ready]);
  await sleep(2500);
  const value = await bridge.ok('param_read', { name: 'SYS_AUTOSTART' });
  assert.equal(value.value, 4001);
  const status = await bridge.waitEvent('link', (d) => d.foreignFrames > 0, 3000, mark);
  assert.equal(status.data.systemId, 1);
  const heartbeats = bridge.since(mark, 'heartbeat');
  assert.ok(heartbeats.length >= 2, 'the pinned vehicle kept reporting');
  assert.ok(heartbeats.every((e) => e.data.armed === false && e.data.modeKey === 'POSCTL'),
    'foreign heartbeats changed no vehicle state');
  for (const intruder of [otherSystem, sameSystemOtherAddress]) {
    assert.deepEqual(intruder.received(), [], 'a foreign sender received no frame');
  }
  assert.ok(peer.received('PARAM_REQUEST_READ').length >= 1, 'the pinned vehicle got the read');
  await bridge.close();
  console.log('  ok other system id and same id from another address: no state change, no frame sent to them');
}

async function exitsWithin(bridge, action, what) {
  const started = Date.now();
  action();
  const result = await Promise.race([bridge.child.exited, sleep(2000).then(() => null)]);
  assert.ok(result, `sidecar still running 2 s after ${what}`);
  assert.equal(result.code, 0, `${what} exit code (signal ${result.signal})\n${bridge.stderr}`);
  return Date.now() - started;
}

async function lifecycle() {
  const cases = [
    ['stdin close', (b) => b.child.stdin.end()],
    ['SIGTERM', (b) => b.child.kill('SIGTERM')],
    ['closed stdout', (b) => b.child.stdout.destroy()],
  ];
  for (const [what, action] of cases) {
    const { port, bridge, peer } = await connected();
    await bridge.waitEvent('attitude');
    const ms = await exitsWithin(bridge, () => action(bridge), what);
    const again = new Bridge();
    await again.ok('connect', { transport: 'udp', port });
    await again.close();
    await peer.stop();
    console.log(`  ok ${what}: exit 0 in ${ms} ms and the UDP port is free again`);
  }
}

async function stalledReader() {
  const { bridge, peer } = await connected();
  const gcsHeartbeats = () => peer.received('HEARTBEAT').filter((e) => e.sysid === 255).length;
  const before = gcsHeartbeats();
  const mark = bridge.events.length;
  // 9 s is longer than the pipe plus the 256-event queue can hold (about 6 s of telemetry).
  bridge.child.stdout.pause();
  await sleep(9000);
  const during = gcsHeartbeats() - before;
  bridge.child.stdout.resume();
  assert.ok(during >= 8, `GCS heartbeats while stdout was not read: ${during}`);
  const hello = await bridge.ok('hello');
  assert.equal(hello.protocolVersion, 1);
  // droppedEvents is the count since the previous link status, so look from the stall onward.
  const status = await bridge.waitEvent('link', (d) => d.droppedEvents > 0, 3000, mark);
  assert.equal(status.data.state, 'connected');
  await bridge.close();
  await peer.stop();
  console.log(`  ok a reader stalled for 9 s: ${during} heartbeats still reached the vehicle, old telemetry dropped`);
}

async function heartbeatWatchdog() {
  const { bridge, peer } = await connected();
  const mark = bridge.events.length;
  const muted = Date.now();
  peer.child.kill('SIGUSR1');
  const lost = await bridge.waitEvent('link', (d) => d.state === 'lost', 5000, mark);
  const lostAfter = Date.now() - muted;
  assert.ok(lostAfter >= 2500, `lost after only ${lostAfter} ms of silence`);
  const resumed = Date.now();
  peer.child.kill('SIGUSR1');
  const back = bridge.events.indexOf(lost);
  await bridge.waitEvent('link', (d) => d.state === 'connected', 3000, back);
  await bridge.close();
  await peer.stop();
  console.log(`  ok watchdog: lost after ${lostAfter} ms of silence, connected ${Date.now() - resumed} ms after heartbeats resumed`);
}

async function run() {
  try {
    await heartbeatWatchdog();
    await foreignSenders();
    await lifecycle();
    await stalledReader();
  } finally {
    await killAll();
  }
}

module.exports = { run };
