// Shared harness for the sidecar tests: spawns the Python sidecar and the
// vehicle peer, sends commands, waits for replies and events, validates every
// sidecar output line against the protocol schema and kills every child.
const assert = require('assert');
const { spawn } = require('child_process');
const dgram = require('dgram');
const fs = require('fs');
const os = require('os');
const path = require('path');
const readline = require('readline');
const { createValidator } = require('./schema-validator');

const EXT_DIR = path.resolve(__dirname, '..');
const PYTHON_DIR = path.join(EXT_DIR, 'python');
const PEER = path.join(__dirname, 'fixtures', 'sim_vehicle_peer.py');
const PYTHON = process.env.PX4_GCS_TEST_PYTHON || 'python3';
const validator = createValidator();
const children = new Set();

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function track(child) {
  children.add(child);
  child.exited = new Promise((resolve) => child.on('exit', (code, signal) => {
    children.delete(child);
    resolve({ code, signal });
  }));
  return child;
}

async function killAll() {
  const pending = [...children].map((child) => {
    child.kill('SIGKILL');
    return child.exited;
  });
  await Promise.all(pending);
}

function tempDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function freeUdpPort() {
  return new Promise((resolve, reject) => {
    const socket = dgram.createSocket('udp4');
    socket.on('error', reject);
    socket.bind(0, '127.0.0.1', () => {
      const { port } = socket.address();
      socket.close(() => resolve(port));
    });
  });
}

async function waitFor(predicate, timeoutMs, what) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = predicate();
    if (value) return value;
    if (Date.now() > deadline) assert.fail(`timed out after ${timeoutMs} ms waiting for ${what}`);
    await sleep(25);
  }
}

class Bridge {
  constructor(env = {}) {
    this.child = track(spawn(PYTHON, ['-m', 'px4_gcs_bridge'], {
      cwd: PYTHON_DIR,
      env: { ...process.env, PYTHONPATH: PYTHON_DIR, ...env },
      stdio: ['pipe', 'pipe', 'pipe'],
    }));
    this.nextId = 1;
    this.pending = new Map();
    this.events = [];
    this.lines = 0;
    this.stderr = '';
    this.child.stderr.on('data', (chunk) => { this.stderr += chunk; });
    this.child.stdin.on('error', () => {});
    readline.createInterface({ input: this.child.stdout }).on('line', (text) => this.onLine(text));
  }

  onLine(text) {
    const message = JSON.parse(text);
    validator.line(message);
    this.lines += 1;
    if (message.type === 'event') {
      this.events.push(message);
      return;
    }
    const waiter = this.pending.get(message.id);
    if (waiter) {
      this.pending.delete(message.id);
      waiter(message);
    } else {
      this.events.push({ type: 'orphan-reply', reply: message });
    }
  }

  start(cmd, args) {
    const id = this.nextId++;
    const command = args === undefined ? { id, cmd } : { id, cmd, args };
    validator.command(command);
    const reply = new Promise((resolve) => this.pending.set(id, resolve));
    this.child.stdin.write(`${JSON.stringify(command)}\n`);
    return { id, reply };
  }

  async send(cmd, args, timeoutMs = 15000) {
    const { reply } = this.start(cmd, args);
    let timer;
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`no reply to ${cmd} within ${timeoutMs} ms\n${this.stderr}`)), timeoutMs);
    });
    try {
      return await Promise.race([reply, timeout]);
    } finally {
      clearTimeout(timer);
    }
  }

  async ok(cmd, args, timeoutMs) {
    const reply = await this.send(cmd, args, timeoutMs);
    assert.ok(reply.ok, `${cmd} failed: ${JSON.stringify(reply.error)}`);
    return reply.data;
  }

  async fail(cmd, args, code, timeoutMs) {
    const reply = await this.send(cmd, args, timeoutMs);
    assert.ok(!reply.ok, `${cmd} should fail with ${code}`);
    assert.equal(reply.error.code, code, `${cmd}: ${JSON.stringify(reply.error)}`);
    return reply.error;
  }

  since(mark, name) {
    return this.events.slice(mark).filter((e) => e.name === name);
  }

  waitEvent(name, predicate = () => true, timeoutMs = 5000, from = 0) {
    return waitFor(() => this.events.slice(from).find((e) => e.name === name && predicate(e.data)),
      timeoutMs, `event ${name}`);
  }

  async close() {
    this.child.stdin.end();
    const result = await Promise.race([this.child.exited, sleep(3000).then(() => null)]);
    assert.ok(result, 'sidecar did not exit within 3 s after stdin closed');
    assert.equal(result.code, 0, `sidecar exit code\n${this.stderr}`);
  }
}

class Peer {
  constructor({ udpTarget, pty = false, sysid = 1, config = {}, bindPort = 0 }) {
    this.dir = tempDir('px4-gcs-peer-');
    this.logPath = path.join(this.dir, 'peer.jsonl');
    const args = [PEER, '--log', this.logPath, '--sysid', String(sysid), '--config', JSON.stringify(config)];
    if (pty) args.push('--pty');
    else args.push('--udp-target', udpTarget, '--bind-port', String(bindPort));
    this.child = track(spawn(PYTHON, args, { stdio: ['ignore', 'pipe', 'pipe'] }));
    this.stderr = '';
    this.child.stderr.on('data', (chunk) => { this.stderr += chunk; });
    // A peer that dies before announcing itself must fail the suite, not leave `ready` pending.
    this.ready = Promise.race([
      new Promise((resolve) => {
        readline.createInterface({ input: this.child.stdout }).once('line', (line) => resolve(JSON.parse(line)));
      }),
      this.child.exited.then((r) => { throw new Error(`peer exited (${JSON.stringify(r)}) before ready\n${this.stderr}`); }),
    ]);
  }

  log() {
    if (!fs.existsSync(this.logPath)) return [];
    return fs.readFileSync(this.logPath, 'utf8').split('\n').filter(Boolean).map((line) => JSON.parse(line));
  }

  received(type) {
    return this.log().filter((entry) => entry.kind === 'rx' && (!type || entry.type === type));
  }

  /** The vehicle arms by itself and sends a heartbeat at once. */
  selfArm() {
    this.child.kill('SIGUSR2');
  }

  async stop() {
    this.child.kill('SIGTERM');
    await Promise.race([this.child.exited, sleep(2000)]);
  }
}

module.exports = { Bridge, Peer, PYTHON, PYTHON_DIR, freeUdpPort, killAll, sleep, tempDir, waitFor, track };
