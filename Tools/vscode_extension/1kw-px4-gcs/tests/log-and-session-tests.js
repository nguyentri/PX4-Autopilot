// Logs and recording against the real sidecar and the PX4-like peer: the log
// list, a lossy download whose SHA-256 must equal the source, cancel (no
// partial file, LOG_REQUEST_END sent), GCS heartbeats during a download, and a
// .tlog that pymavlink reads back, closed on stdin EOF. Host-side services and
// the HTML report are tested in log-and-session-host-tests.js.
const assert = require('assert');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { Bridge, Peer, PYTHON, freeUdpPort, sleep, tempDir, waitFor } = require('./bridge-test-harness');
const hostTests = require('./log-and-session-host-tests');

async function pair(config) {
  const port = await freeUdpPort();
  const peer = new Peer({ udpTarget: `127.0.0.1:${port}`, config });
  await peer.ready;
  const bridge = new Bridge();
  await bridge.ok('connect', { transport: 'udp', port });
  return { bridge, peer };
}

const sourceSha = (peer) => peer.log().find((e) => e.kind === 'log_source');

async function listAndLossyDownload() {
  const { bridge, peer } = await pair({ log: { size: 400000, seed: 11, loss: 0.05 } });
  const list = await bridge.ok('log_list', undefined, 10000);
  assert.equal(list.answered, true);
  assert.deepEqual(list.entries.map((e) => [e.id, e.size]), [[1, 400000]], 'list matches the peer');
  const dir = tempDir('px4-gcs-log-');
  const dest = path.join(dir, 'log-1.ulg');
  const hbBefore = peer.received('HEARTBEAT').length;
  const t0 = Date.now();
  const op = bridge.start('log_download', { id: 1, size: 400000, path: dest });
  const reply = await Promise.race([op.reply, sleep(60000).then(() => ({ ok: false, error: { code: 'TEST_TIMEOUT' } }))]);
  assert.ok(reply.ok, `download: ${JSON.stringify(reply.error)}\n${bridge.stderr}`);
  const seconds = (Date.now() - t0) / 1000;
  const source = sourceSha(peer);
  assert.equal(reply.data.sha256, source.sha256, 'downloaded SHA-256 equals the source with 5 % loss');
  assert.ok(reply.data.requests > 1, 'lost chunks were asked for again');
  assert.equal(fs.readFileSync(dest).subarray(0, 4).toString(), 'ULog');
  assert.ok(!fs.existsSync(`${dest}.part`), 'no .part file left');
  const progress = bridge.events.filter((e) => e.name === 'log_progress' && e.data.id === op.id);
  assert.ok(progress.length >= 2 && progress.at(-1).data.received === 400000, 'progress keyed by the command id');
  const beats = peer.received('HEARTBEAT').length - hbBefore;
  assert.ok(seconds < 2 || beats >= Math.floor(seconds) - 1, `GCS heartbeats continue: ${beats} in ${seconds.toFixed(1)} s`);
  await waitFor(() => peer.received('LOG_REQUEST_END').length >= 1, 2000, 'LOG_REQUEST_END after success');
  await bridge.close();
  await peer.stop();
  console.log(`  ok list, 400 kB download at 5 % loss in ${seconds.toFixed(1)} s (${reply.data.requests} requests), `
    + `SHA-256 matches, ${beats} GCS heartbeats meanwhile`);
}

async function cancelledDownload() {
  const { bridge, peer } = await pair({ log: { size: 400000, seed: 3, chunksPerPass: 2 } });
  const dir = tempDir('px4-gcs-log-');
  const dest = path.join(dir, 'log-1.ulg');
  const op = bridge.start('log_download', { id: 1, size: 400000, path: dest });
  await bridge.waitEvent('log_progress', (d) => d.id === op.id && d.received > 0, 5000);
  // PX4 ends a running transfer when it gets LOG_REQUEST_LIST: no list during a download, and a refusal is answered.
  const listRequests = peer.received('LOG_REQUEST_LIST').length;
  await bridge.fail('log_list', undefined, 'BAD_ARGUMENT', 3000);
  await bridge.fail('log_download', { id: 1, size: 400000, path: dest }, 'BAD_ARGUMENT', 3000);
  assert.equal(peer.received('LOG_REQUEST_LIST').length, listRequests, 'no LOG_REQUEST_LIST sent during the download');
  assert.equal((await bridge.ok('cancel', { target: op.id })).cancelled, true);
  const reply = await op.reply;
  assert.equal(reply.error.code, 'CANCELLED');
  assert.deepEqual(fs.readdirSync(dir), [], 'no partial file after cancel');
  await waitFor(() => peer.received('LOG_REQUEST_END').length >= 1, 2000, 'LOG_REQUEST_END after cancel');
  await bridge.fail('log_download', { id: 1, size: 10, path: 'relative.ulg' }, 'BAD_ARGUMENT');
  await bridge.close();
  await peer.stop();
  console.log('  ok cancel: CANCELLED, no partial file, LOG_REQUEST_END sent; relative path refused; '
    + 'list and second download refused during a download');
}

/** Read a .tlog with pymavlink: [type, timestamp] per record. */
function readTlog(file) {
  const script = [
    'import json, sys',
    'from pymavlink import mavutil',
    'm = mavutil.mavlink_connection(sys.argv[1], dialect="development")',
    'out = []',
    'while True:',
    '    msg = m.recv_match()',
    '    if msg is None: break',
    '    out.append([msg.get_type(), msg._timestamp, msg.get_srcSystem()])',
    'print(json.dumps(out))',
  ].join('\n');
  return JSON.parse(execFileSync(PYTHON, ['-c', script, file], { encoding: 'utf8' }));
}

async function recording() {
  const { bridge, peer } = await pair({});
  const dir = tempDir('px4-gcs-rec-');
  await sleep(500);
  assert.deepEqual(fs.readdirSync(dir), [], 'no recording without an explicit start');
  await bridge.fail('record_start', { path: path.join(dir, 'x.txt') }, 'BAD_ARGUMENT');
  const file = path.join(dir, 'px4-gcs-test.tlog');
  await bridge.ok('record_start', { path: file });
  await bridge.waitEvent('recording', (d) => d.state === 'started');
  await bridge.fail('record_start', { path: path.join(dir, 'second.tlog') }, 'BAD_ARGUMENT');
  await bridge.ok('log_list', undefined, 10000);
  await sleep(1200);
  const stopped = await bridge.ok('record_stop');
  assert.ok(stopped.stopped && stopped.frames > 10, `frames recorded: ${stopped.frames}`);
  const records = readTlog(file);
  const types = new Set(records.map((r) => r[0]));
  for (const t of ['HEARTBEAT', 'LOG_REQUEST_LIST', 'LOG_ENTRY', 'ATTITUDE']) assert.ok(types.has(t), `.tlog has ${t}`);
  assert.ok(records.some((r) => r[0] === 'HEARTBEAT' && r[2] === 255), 'GCS heartbeats (sent frames) are recorded');
  assert.ok(records.every((r, i) => i === 0 || r[1] >= records[i - 1][1]), 'timestamps never decrease');
  assert.equal(records.length, stopped.frames, 'every record decodes');

  const eof = path.join(dir, 'px4-gcs-eof.tlog');
  await bridge.ok('record_start', { path: eof });
  await sleep(600);
  await bridge.close();
  const tail = readTlog(eof);
  assert.ok(tail.length > 3 && tail.some((r) => r[0] === 'HEARTBEAT'), 'the recording closed cleanly on stdin EOF');
  await peer.stop();
  console.log(`  ok .tlog: ${records.length} frames read back by pymavlink (RX and TX), closed on stdin EOF`);
}

async function run(ctx) {
  await listAndLossyDownload();
  await cancelledDownload();
  await recording();
  await hostTests.run(ctx);
}

module.exports = { run };
