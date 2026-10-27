const assert = require('assert');
const cp = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const Module = require('module');
const net = require('net');
const esbuild = require('../node_modules/esbuild');

async function runConsoleTests() {
  const root = path.resolve(__dirname, '../../..');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'console terminal '));
  const originalPath = process.env.PATH;
  const previousRuntime = process.env.FIRMWARE_WORKSPACE_RUNTIME;
  const children = []; const fixtureClients = [];
  const originalLoad = Module._load;
  const terminals = [];
  let pidGate;
  let serialPath = '/dev/null';
  let current = true;
  let blocked = false;
  let transport = 'rtt'; const transports = {};
  let stops = 0, releases = 0, starts = 0;
  let stopFails = false, startFails = false, recoveryRequired = false;
  let doctorStatus = 'ok', missingHistory = false;
  let endpoint = '127.0.0.1:19021';
  class EventEmitter {
    constructor() { this.listeners = []; this.event = (fn) => { this.listeners.push(fn); return { dispose() {} }; }; }
    fire(value) { for (const fn of this.listeners) { fn(value); } }
    dispose() { this.listeners = []; }
  }
  const closed = new EventEmitter();
  const errors = [];
  const vscode = {
    EventEmitter, Uri: { file: (value) => ({ fsPath: value }) },
    workspace: { isTrusted: true, getConfiguration: () => ({ get: (_, fallback) => fallback }) },
    window: {
      showErrorMessage: async (error) => errors.push(error), onDidCloseTerminal: closed.event,
      createTerminal(options) {
        const terminal = { options, shown: 0, show() { this.shown++; }, dispose() { this.disposed = true; closed.fire(this); options.pty?.close(); } };
        if (options.pty) { options.pty.onDidWrite((data) => { terminal.output = (terminal.output || '') + data; }); options.pty.open(); }
        else {
          const child = cp.spawn(options.shellPath, options.shellArgs, { cwd: options.cwd, env: { ...process.env, ...options.env } });
          children.push(child); terminal.child = child;
          child.stdout.on('data', () => {}); child.stderr.on('data', () => {});
          child.on('exit', (code) => { terminal.exitStatus = { code }; closed.fire(terminal); });
          terminal.processId = pidGate ? pidGate.then(() => child.pid) : Promise.resolve(child.pid);
        }
        terminals.push(terminal); return terminal;
      },
    },
  };
  const token = { setupId: 'one', revision: 1, probe: 'probe', core: 'cr8_0' };
  const pair = { generation: 1, sources: {}, prepared: { receiptId: 'captured', pairSha256: 'a'.repeat(64), artifacts: [] } };
  const store = {
    assertMutable() { if (blocked) { throw new Error('busy'); } }, getSelection: () => ({ id: 'fixed', board: 'rdk-rzv2h', group: 'group' }),
    getActiveSetup: () => ({ id: 'one', name: 'My setup' }), getConsoleTransport: (core) => transports[core] || transport,
    captureSetupToken: () => token, isSetupTokenCurrent: () => current, getConsoleDevice: () => serialPath,
    getPreparedPair: () => pair, getReceiptPath: () => '/exact/captured.json', getSelectedProbe: () => 'probe',
    writeSelectionSnapshot: () => '/exact/selection.json',
    updatePreparedPair: async (_, update) => Object.assign(pair, update(pair)),
  };
  const client = {
    getWorkspaceRoot: () => root,
    probeLeases: { acquire: async (serial) => ({ lease: { serial, leaseToken: 'own' }, release: async () => { releases++; } }) },
    consoleAction: async (action, selection, receipt, serial, options) => {
      assert.equal(selection, '/exact/selection.json'); assert.equal(receipt, '/exact/captured.json'); assert.equal(serial, 'probe'); assert.ok(['cr8_0', 'cr8_1'].includes(options.core));
      if (action === 'stop') { stops++; return { status: stopFails ? 'failed' : 'ok', data: {} }; }
      starts++; if (startFails) { recoveryRequired = true; return { status: 'failed', diagnostics: [{ message: 'CONSOLE_START_FAILED' }] }; } return { status: 'ok', data: { endpoint, running: true, core: options.core, transport: 'rtt' } };
    },
    runDoctor: async () => ({ status: doctorStatus, diagnostics: doctorStatus === 'failed' ? [{ code: 'MISSING_ARM_GCC' }] : [], data: { targetHistory: missingHistory ? undefined : { recoveryRequired, verifiedPair: { pairSha256: 'a'.repeat(64) } } } }),
  };
  let controller, server;
  const sockets = new Set();
  const wait = async (predicate) => { for (let i = 0; i < 400 && !predicate(); i++) { await new Promise((r) => setTimeout(r, 10)); } assert.ok(predicate(), 'asynchronous condition timed out'); };
  try {
    Module._load = function(name, parent, main) { return name === 'vscode' ? vscode : originalLoad.call(this, name, parent, main); };
    const file = path.resolve(__dirname, '../src/console-terminal-controller.ts');
    const output = esbuild.buildSync({ entryPoints: [file], bundle: true, platform: 'node', format: 'cjs', write: false, external: ['vscode'] }).outputFiles[0].text;
    const compiled = new Module(file, module); compiled.filename = file; compiled.paths = Module._nodeModulePaths(path.dirname(file)); compiled._compile(output, file);
    const Controller = compiled.exports.ConsoleTerminalController;
    controller = new Controller(client, store);
    server = net.createServer((socket) => { sockets.add(socket); socket.on('data', (data) => socket.write(data)); socket.on('close', () => sockets.delete(socket)); });
    await new Promise((resolve, reject) => { server.once('error', reject); server.listen(19021, '127.0.0.1', resolve); });
    assert.equal(await controller.startCoreConsole('cr8_0'), true);
    const terminal = terminals.at(-1); terminal.options.pty.handleInput('ipctest\r');
    await wait(() => terminal.output.includes('ipctest'));
    assert.ok(terminal.output.includes('not live proof'));
    assert.equal(await controller.startCoreConsole('cr8_0'), true); assert.equal(starts, 1, 'same owned console reuses terminal');
    stopFails = true;
    await assert.rejects(controller.stopOwnedSessions(), /reservation retained/);
    assert.equal(controller.hasOwnedSessions(), true); assert.equal(releases, 0);
    assert.equal((await controller.stopRttForDebugHandoff()).ok, false);
    stopFails = false;
    const handoff = await controller.stopRttForDebugHandoff(); assert.equal(handoff.ok, true); assert.ok(handoff.lease);
    assert.equal(releases, 0); await handoff.lease.release(); assert.equal(releases, 1); assert.equal(controller.hasOwnedSessions(), false);
    doctorStatus = 'failed';
    assert.equal(await controller.startCoreConsole('cr8_0'), true, 'missing build tools must not invalidate verified loaded-pair history');
    await controller.stopOwnedSessions();
    missingHistory = true; const startsWithoutHistory = starts;
    await assert.rejects(controller.startCoreConsole('cr8_0'), /diagnose/);
    assert.equal(starts, startsWithoutHistory, 'missing history remains blocked before probe access');
    missingHistory = false; doctorStatus = 'ok';
    endpoint = 'untrusted.example:19021';
    await assert.rejects(controller.startCoreConsole('cr8_0'), /unexpected endpoint/);
    assert.equal(controller.hasOwnedSessions(), false); assert.ok(stops >= 3); endpoint = '127.0.0.1:19021';
    startFails = true; await assert.rejects(controller.startCoreConsole('cr8_0'), /CONSOLE_START_FAILED/);
    assert.equal(pair.history.message, 'Recover Both required');
    const startsAfterFailure = starts;
    await assert.rejects(controller.startCoreConsole('cr8_0'), /diagnose/); assert.equal(starts, startsAfterFailure);
    recoveryRequired = false; startFails = false;
    vscode.workspace.isTrusted = false; await assert.rejects(controller.startCoreConsole('cr8_0'), /Trust/); vscode.workspace.isTrusted = true;
    const probeStartsBeforeSerial = starts;
    transport = 'sci4';
    const bin = path.join(temp, 'bin with spaces'); fs.mkdirSync(bin);
    fs.writeFileSync(path.join(bin, 'picocom'), '#!/usr/bin/env python3\nimport time\nwhile True: time.sleep(0.1)\n'); fs.chmodSync(path.join(bin, 'picocom'), 0o755);
    process.env.PATH = bin + path.delimiter + originalPath; process.env.FIRMWARE_WORKSPACE_RUNTIME = path.join(temp, 'runtime');
    const alias = path.join(temp, 'uart with spaces'); fs.symlinkSync('/dev/null', alias); serialPath = alias;
    delete pair.validationError;
    assert.equal(await controller.startCoreConsole('cr8_0'), true);
    const uart = terminals.at(-1); assert.ok(uart.options.isTransient); assert.equal(uart.options.shellPath, 'python3');
    assert.deepEqual(uart.options.shellArgs.slice(0, 6), ['-m', 'firmware_workspace.serial_console', '--device', '/dev/null', '--baud', '115200']);
    assert.equal(starts, probeStartsBeforeSerial, 'SCI4 must not start a probe console');
    await controller.stopOwnedSessions(); await wait(() => uart.exitStatus !== undefined); assert.equal(controller.hasOwnedSessions(), false);
    transports.cr8_1 = 'rtt';
    await controller.startCoreConsole('cr8_0'); const coexistSerial = terminals.at(-1);
    await controller.startCoreConsole('cr8_1');
    assert.ok(controller.describe('cr8_0').includes('SCI4')); assert.ok(controller.describe('cr8_1').includes('RTT'));
    stopFails = true;
    await assert.rejects(controller.stopOwnedSessions(), /reservation retained/);
    await wait(() => coexistSerial.exitStatus !== undefined);
    assert.equal(controller.describe('cr8_0'), undefined, 'one failed RTT stop must not prevent UART teardown');
    assert.ok(controller.describe('cr8_1'));
    stopFails = false; await controller.stopOwnedSessions(); delete transports.cr8_1;
    // Supervisor death cannot free a UART inherited by the exact client.
    await controller.startCoreConsole('cr8_0');
    const crashed = terminals.at(-1);
    const metadata = fs.readdirSync(path.join(temp, 'runtime', 'uart')).filter((name) => name.endsWith('.json'))
      .map((name) => JSON.parse(fs.readFileSync(path.join(temp, 'runtime', 'uart', name))))
      .find((meta) => crashed.options.shellArgs.includes(meta.sessionId));
    assert.ok(metadata.childPid); fixtureClients.push(metadata);
    crashed.child.kill('SIGKILL'); await wait(() => crashed.exitStatus !== undefined);
    await assert.rejects(controller.stopOwnedSessions(), /kernel lease remains busy/);
    assert.equal(controller.hasOwnedSessions(), true, 'supervisor death does not authorize killing its inherited client');
    // Fixture owns this exact child. Product cleanup never signals a metadata PID.
    process.kill(metadata.childPid, 'SIGTERM');
    await new Promise((resolve) => setTimeout(resolve, 50));
    await controller.stopOwnedSessions(); assert.equal(controller.hasOwnedSessions(), false);
    // UI close wins before processId resolves. Still observe and reap only this launch.
    let releasePid; pidGate = new Promise((resolve) => { releasePid = resolve; });
    const starting = controller.startCoreConsole('cr8_0');
    const late = terminals.at(-1); late.dispose(); releasePid();
    await assert.rejects(starting, /cancelled/); await wait(() => late.exitStatus !== undefined); assert.equal(controller.hasOwnedSessions(), false);
    pidGate = undefined;
    // Device/probe change before a late PID must not publish a session.
    let releaseStale; pidGate = new Promise((resolve) => { releaseStale = resolve; });
    const stale = controller.startCoreConsole('cr8_0'); current = false; releaseStale();
    await assert.rejects(stale, /changed/); current = true; pidGate = undefined;
    await controller.disposeAsync();
    console.log('  ✓ interactive RTT, exact handoff, retained failed owner, SCI4 argv, stale PID, close/start and trust contracts');
  } finally {
    for (const meta of fixtureClients) {
      try { const start = fs.readFileSync(`/proc/${meta.childPid}/stat`, 'utf8').split(')').slice(1).join(')').trim().split(/\s+/)[19]; if (start === meta.childStart) { process.kill(meta.childPid, 'SIGTERM'); } } catch {}
    }
    for (const child of children) { if (child.exitCode === null && child.signalCode === null) { child.kill('SIGTERM'); } }
    await controller?.disposeAsync().catch(() => undefined);
    for (const socket of sockets) { socket.destroy(); }
    if (server?.listening) { await new Promise((resolve) => server.close(resolve)); }
    Module._load = originalLoad; process.env.PATH = originalPath;
    if (previousRuntime === undefined) { delete process.env.FIRMWARE_WORKSPACE_RUNTIME; } else { process.env.FIRMWARE_WORKSPACE_RUNTIME = previousRuntime; }
    fs.rmSync(temp, { recursive: true, force: true });
  }
}
module.exports = runConsoleTests;
if (require.main === module) { runConsoleTests().catch((error) => { console.error(error); process.exitCode = 1; }); }
