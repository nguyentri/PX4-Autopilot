// Sidecar protocol over real loopback UDP against the PX4-like vehicle peer:
// hello/doctor, telemetry decode, parameters, guarded commands, streams,
// shell and inspector. Every sidecar line is schema-validated by the harness.
const assert = require('assert');
const dgram = require('dgram');
const { Bridge, Peer, freeUdpPort, killAll, sleep, waitFor } = require('./bridge-test-harness');

const TELEMETRY = ['attitude', 'position', 'local_position', 'gps', 'battery', 'vfr', 'named_value', 'heartbeat'];

async function helloAndDoctor() {
  const bridge = new Bridge();
  const hello = await bridge.ok('hello');
  assert.equal(hello.protocolVersion, 1);
  assert.ok(hello.commands.includes('param_set'));
  assert.ok(hello.modes.some((m) => m.key === 'AUTO_LOITER'), 'hello carries the mode table');
  const doctor = await bridge.ok('doctor');
  assert.equal(doctor.pythonOk, true);
  assert.deepEqual(doctor.missing, []);
  await bridge.fail('arm', undefined, 'NOT_CONNECTED');
  await bridge.close();
  console.log('  ok hello with the mode table, doctor, NOT_CONNECTED before connect');
}

async function telemetryAndStatusText(bridge) {
  for (const name of TELEMETRY) await bridge.waitEvent(name);
  for (const kind of ['imu', 'baro', 'distance']) await bridge.waitEvent('sensors', (d) => d.kind === kind);
  const imu = await bridge.waitEvent('sensors', (d) => d.kind === 'imu');
  assert.equal(imu.data.source, 'HIGHRES_IMU');
  const hb = await bridge.waitEvent('heartbeat');
  assert.equal(hb.data.modeKey, 'POSCTL');
  assert.equal(hb.data.armed, false);
  const text = await bridge.waitEvent('statustext', (d) => d.id === 7);
  assert.equal(text.data.text, `${'A'.repeat(50)}BC end`);
  assert.equal(text.data.partial, false);
  await bridge.waitEvent('statustext', (d) => d.partial === true, 6000);
  await bridge.waitEvent('link', (d) => d.droppedStatusText > 0, 6000);
  const modes = await bridge.waitEvent('modes');
  assert.deepEqual(modes.data.available, ['MANUAL', 'POSCTL', 'AUTO_LOITER', 'AUTO_RTL', 'AUTO_LAND']);
  console.log('  ok every telemetry event, HIGHRES_IMU, STATUSTEXT reassembly and pending-id cap, modes');
}

async function parameters(bridge, peer) {
  const list = await bridge.ok('param_list', undefined, 20000);
  const names = list.params.map((p) => p.name);
  assert.equal(list.count, 41, 'the vehicle count includes the internal parameter');
  assert.equal(list.params.length, 40, `visible params, missing ${JSON.stringify(list.missing)}`);
  assert.deepEqual(list.missing, []);
  assert.ok(!names.includes('_HASH_CHECK') && !names.includes('_INTERNAL_X'), 'hidden parameters stay hidden');
  assert.ok(names.includes('SYS_AUTOSTART') && names.includes('TEST_F07'), 'dropped indices were recovered');
  assert.equal(list.params.find((p) => p.name === 'NAN_BITS_INT').value, 0x7F800001, 'int32 is not a float');
  assert.equal(list.params.find((p) => p.name === 'NEG_INT_PARAM').value, -1);
  assert.ok(bridge.events.some((e) => e.name === 'param_progress'));

  const float = await bridge.ok('param_set', { name: 'TEST_F00', value: 2.5 });
  assert.deepEqual([float.applied, float.value, float.type, float.echoed], [true, 2.5, 'REAL32', true]);
  const int = await bridge.ok('param_set', { name: 'NEG_INT_PARAM', value: -7 });
  assert.deepEqual([int.applied, int.value, int.type], [true, -7, 'INT32']);
  const sets = peer.log().filter((e) => e.kind === 'param_set');
  assert.equal(sets.find((e) => e.name === 'NEG_INT_PARAM').type, 6, 'int32 written with the reported type');
  assert.equal(sets.find((e) => e.name === 'NEG_INT_PARAM').raw, 'f9ffffff');
  await bridge.fail('param_set', { name: '_INTERNAL_X', value: 1 }, 'BAD_ARGUMENT');
  const silentApplied = await bridge.ok('param_set', { name: 'TEST_F01', value: 9.5 });
  assert.deepEqual([silentApplied.applied, silentApplied.echoed, silentApplied.value], [true, false, 9.5]);
  const silentRejected = await bridge.ok('param_set', { name: 'TEST_F02', value: 9.5 });
  assert.deepEqual([silentRejected.applied, silentRejected.value], [false, 1.0], 'read-back shows the held value');
  console.log('  ok param_list after drops with hidden names, set float/int32, "_" refusal, silent writes read back');
}

async function commands(bridge) {
  const mark = bridge.events.length;
  await bridge.ok('arm');
  await bridge.waitEvent('heartbeat', (d) => d.armed === true, 3000, mark);
  await bridge.ok('set_mode', { mode: 'AUTO_LOITER' });
  await bridge.waitEvent('heartbeat', (d) => d.modeKey === 'AUTO_LOITER' && d.mainMode === 4 && d.subMode === 3, 3000, mark);
  await bridge.fail('set_mode', { mode: 'NOT_A_MODE' }, 'BAD_ARGUMENT');
  await bridge.ok('disarm');
  await bridge.waitEvent('heartbeat', (d) => d.armed === false, 3000, bridge.events.length - 1);
  console.log('  ok arm accepted, mode change in the next heartbeat, disarm');
}

async function streams(bridge, peer) {
  const request = await bridge.ok('stream_request', { message: 30, intervalUs: 100000 });
  assert.equal(request.originalUs, 20000);
  const release = await bridge.ok('stream_release', { message: 30 });
  assert.equal(release.restoredUs, 20000);
  await bridge.fail('stream_request', { message: 0, intervalUs: 100000 }, 'BAD_ARGUMENT');
  await bridge.fail('stream_request', { message: 33, intervalUs: 100000 }, 'DENIED');
  const sets = peer.log().filter((e) => e.kind === 'interval_set');
  assert.deepEqual(sets.map((e) => [e.message, e.interval]), [[30, 100000], [30, 20000]]);
  assert.ok(!sets.some((e) => e.interval === 0), 'interval 0 never reaches the vehicle');
  console.log('  ok stream request/release restores the original interval; unknown interval refused');
}

async function shellAndInspector(bridge, peer) {
  const first = peer.received()[0];
  assert.equal(first.type, 'SERIAL_CONTROL', 'shell close is the first frame after connect');
  const firstShell = peer.log().find((e) => e.kind === 'shell');
  assert.deepEqual([firstShell.flags, firstShell.count], [0, 0], 'the first shell frame is a close');
  await bridge.ok('shell_open');
  await bridge.waitEvent('shell_data', (d) => d.text.includes('nsh> '));
  const mark = bridge.events.length;
  assert.equal((await bridge.ok('shell_write', { data: 'ls\n' })).bytes, 3);
  await bridge.waitEvent('shell_data', (d) => d.text.includes('ls\nnsh> '), 3000, mark);
  await bridge.ok('inspector_subscribe');
  const inspector = await bridge.waitEvent('inspector', (d) => d.messages.some((m) => m.name === 'ATTITUDE' && m.last));
  assert.ok(inspector.data.messages.find((m) => m.name === 'ATTITUDE').rateHz > 5);
  await bridge.ok('inspector_unsubscribe');
  await sleep(800);
  const after = bridge.events.length;
  await sleep(1200);
  assert.equal(bridge.since(after, 'inspector').length, 0, 'no inspector events after unsubscribe');
  console.log('  ok shell close on connect, shell echo, inspector subscribe/unsubscribe');
}

async function udpPortFree(port) {
  const socket = dgram.createSocket('udp4');
  await new Promise((resolve, reject) => {
    socket.once('error', reject);
    socket.bind(port, '127.0.0.1', resolve);
  });
  socket.close();
}

async function mainVehicle() {
  const port = await freeUdpPort();
  const bridge = new Bridge();
  const peer = new Peer({
    udpTarget: `127.0.0.1:${port}`,
    config: { availableModes: true, dropOnce: [3, 27], silentWrite: { TEST_F01: 'apply', TEST_F02: 'reject' }, statustextFlood: 20 },
  });
  await peer.ready;
  const connected = await bridge.ok('connect', { transport: 'udp', port, sessionId: 'protocol-test' });
  assert.deepEqual([connected.state, connected.systemId, connected.autopilot], ['connected', 1, 12]);
  await telemetryAndStatusText(bridge);
  await parameters(bridge, peer);
  await commands(bridge);
  await streams(bridge, peer);
  await shellAndInspector(bridge, peer);
  await bridge.ok('disconnect');
  await bridge.waitEvent('link', (d) => d.state === 'disconnected');
  // The close frame is sent before the link stops; the peer may log it a moment after the link event.
  const lastShell = () => peer.log().filter((e) => e.kind === 'shell').at(-1);
  await waitFor(() => lastShell()?.flags === 0 && lastShell()?.count === 0, 2000, 'shell close on disconnect');
  await udpPortFree(port);
  console.log('  ok disconnect closes the shell and releases the UDP port');
  await bridge.close();
  await peer.stop();
}

async function deniedAndSilentVehicle() {
  const port = await freeUdpPort();
  const bridge = new Bridge();
  const peer = new Peer({
    udpTarget: `127.0.0.1:${port}`,
    config: { imu: 'scaled', decoyAcks: true, ackResults: { 400: 2 }, logListSilent: true, paramRate: 5 },
  });
  await peer.ready;
  await bridge.ok('connect', { transport: 'udp', port });
  const imu = await bridge.waitEvent('sensors', (d) => d.kind === 'imu');
  assert.equal(imu.data.source, 'SCALED_IMU');
  const denied = await bridge.fail('arm', undefined, 'DENIED');
  assert.equal(denied.details.result, 'MAV_RESULT_DENIED', 'decoy ACCEPTED acks did not complete the command');
  const status = await bridge.waitEvent('link', (d) => d.ignoredAcks >= 2, 3000, bridge.events.length - 1);
  assert.ok(status.data.ignoredAcks >= 2);
  const logs = await bridge.ok('log_list', undefined, 10000);
  assert.deepEqual([logs.answered, logs.entries], [false, []]);
  const list = bridge.start('param_list');
  await bridge.waitEvent('param_progress', (d) => d.id === list.id && d.received > 0, 5000);
  assert.equal((await bridge.ok('cancel', { target: list.id })).cancelled, true);
  const cancelled = await list.reply;
  assert.equal(cancelled.error.code, 'CANCELLED');
  await bridge.close();
  await peer.stop();
  console.log('  ok SCALED_IMU, arm denied despite decoy acks, silent log list, cancelled param_list');
}

async function run() {
  try {
    await helloAndDoctor();
    await mainVehicle();
    await deniedAndSilentVehicle();
  } finally {
    await killAll();
  }
}

module.exports = { run };
