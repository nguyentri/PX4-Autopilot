// Link trust (foreign senders change nothing and receive nothing) and sidecar
// lifecycle (stdin close, SIGTERM, closed stdout, stalled reader).
const assert = require('assert');
const { execFileSync } = require('child_process');
const { Bridge, Peer, PYTHON, PYTHON_DIR, freeUdpPort, killAll, sleep } = require('./bridge-test-harness');

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

/** A raising message handler or tick hook must not end the I/O loop (heartbeat, watchdog, dispatch). */
function loopSurvivesHandlerErrors() {
  const script = [
    'import json, sys, time',
    'sys.path.insert(0, sys.argv[1])',
    'from pymavlink.dialects.v20 import common as m',
    'from px4_gcs_bridge.link import Link',
    'from px4_gcs_bridge.vehicle_pin import VehiclePin',
    'hb = m.MAVLink_heartbeat_message(2, 12, 0x80, 0, 4, 3).pack(m.MAVLink(None, srcSystem=1, srcComponent=1))',
    'class Transport:',
    '    writes = 0',
    '    def read(self):',
    '        time.sleep(0.02)',
    '        return [(hb, None)]',
    '    def write(self, *args): Transport.writes += 1',
    'seen = []',
    'def handler(msg):',
    '    seen.append(msg)',
    '    raise AttributeError("handler failed")',
    'def hook(): raise RuntimeError("hook failed")',
    'link = Link(Transport(), VehiclePin(), lambda state: None, handler)',
    'assert link.listen_for_pin(1.0)',
    'link.tick_hooks = [hook]',
    'link.start(); time.sleep(2.5)',
    'print(json.dumps({"alive": link._thread.is_alive(), "seen": len(seen), "writes": Transport.writes,',
    '                  "errors": link.loop_errors, "state": link.state}))',
    'link.stop()',
  ].join('\n');
  const out = execFileSync(PYTHON, ['-c', script, PYTHON_DIR], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  const result = JSON.parse(out.trim().split('\n').at(-1));
  assert.ok(result.alive, `the I/O thread survived: ${JSON.stringify(result)}`);
  assert.ok(result.seen > 20, `messages kept being dispatched: ${result.seen}`);
  assert.ok(result.writes >= 2, `GCS heartbeats kept being sent: ${result.writes}`);
  assert.ok(result.errors > result.seen, 'handler and hook errors were counted');
  assert.equal(result.state, 'connected');
  console.log(`  ok I/O loop survives raising handlers: ${result.seen} frames dispatched, ${result.writes} heartbeats sent`);
}

async function run() {
  try {
    loopSurvivesHandlerErrors();
    await heartbeatWatchdog();
    await foreignSenders();
    await lifecycle();
    await stalledReader();
  } finally {
    await killAll();
  }
}

module.exports = { run };
