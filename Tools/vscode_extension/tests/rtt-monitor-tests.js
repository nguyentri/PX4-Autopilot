// RTT Monitor: socket client, per-core scrollback, Save Log and the trace
// session that pauses the bridge around probe jobs. A local TCP server stands
// in for the JLinkExe RTT telnet port.
const assert = require('assert');
const fs = require('fs');
const net = require('net');
const os = require('os');
const path = require('path');
const Module = require('module');
const esbuild = require('../node_modules/esbuild');

const tick = (ms = 20) => new Promise((resolve) => setTimeout(resolve, ms));
async function until(check, what, timeoutMs = 2000) {
  const end = Date.now() + timeoutMs;
  while (!check()) {
    if (Date.now() > end) { throw new Error(`timed out waiting for ${what}`); }
    await tick(5);
  }
}

/** A fake bridge port; `mode` 'close' drops each client at once (port busy). */
function fakeBridge(mode = 'serve') {
  const received = [];
  const clients = [];
  const server = net.createServer((socket) => {
    if (mode === 'close') { socket.destroy(); return; }
    clients.push(socket);
    socket.setEncoding('utf8');
    socket.on('data', (text) => received.push(text));
    socket.on('error', () => {});
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve({
    endpoint: `127.0.0.1:${server.address().port}`, received, clients,
    write: (text) => clients.at(-1).write(text),
    close: () => new Promise((done) => { for (const client of clients) { client.destroy(); } server.close(done); }),
  })));
}

async function runRttMonitorTests() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rtt monitor '));
  const config = new Map();
  const infos = [];
  const errors = [];
  let clipboard = '';
  const vscode = {
    Uri: { file: (fsPath) => ({ fsPath }), joinPath: (base, ...parts) => ({ fsPath: path.join(base.fsPath, ...parts) }) },
    ConfigurationTarget: { Global: 1 },
    workspace: {
      getConfiguration: () => ({ get: (key, fallback) => (config.has(key) ? config.get(key) : fallback),
        update: async (key, value) => { config.set(key, value); } }),
      onDidChangeConfiguration: () => ({ dispose() {} }),
    },
    env: { clipboard: { writeText: async (text) => { clipboard = text; } } },
    window: { showInformationMessage: async (text) => { infos.push(text); }, showWarningMessage: async () => {},
      showErrorMessage: async (text) => { errors.push(text); } },
    commands: { executeCommand: async () => {} },
  };
  const originalLoad = Module._load;
  Module._load = function(name, parent, main) { return name === 'vscode' ? vscode : originalLoad.call(this, name, parent, main); };
  function source(name) {
    const file = path.resolve(__dirname, '../src', `${name}.ts`);
    const output = esbuild.buildSync({ entryPoints: [file], bundle: true, platform: 'node', format: 'cjs', write: false, external: ['vscode'], logLevel: 'silent' }).outputFiles[0].text;
    const compiled = new Module(file, module);
    compiled.filename = file; compiled.paths = Module._nodeModulePaths(path.dirname(file)); compiled._compile(output, file); return compiled.exports;
  }
  const servers = [];
  try {
    const { parseEndpoint } = source('rtt-monitor/rtt-socket-client');
    const { RttScrollback, logFileName } = source('rtt-monitor/rtt-scrollback');
    const { RttMonitorViewProvider, monitorCsp } = source('rtt-monitor/rtt-monitor-view-provider');
    const { RttTraceSession, defaultTraceCore } = source('rtt-monitor/rtt-trace-session');
    const { resolveTracePlan } = source('rtt-monitor/trace-plan-resolver');

    assert.deepEqual(parseEndpoint('127.0.0.1:19031'), { host: '127.0.0.1', port: 19031 });
    assert.throws(() => parseEndpoint('10.0.0.5:19021'), /127\.0\.0\.1/, 'a non-loopback endpoint must be refused');
    const csp = monitorCsp('vscode-resource:', 'abc');
    assert.match(csp, /script-src 'nonce-abc';/);
    assert.ok(!/script-src[^;]*unsafe-inline/.test(csp), 'scripts must never allow inline code');
    assert.match(logFileName('Demo Pair #2', 'cr8_1', new Date(2026, 10, 10, 9, 5, 7)), /^demo-pair-2-cr8_1-261110-090507\.log$/);
    const ring = new RttScrollback(100);
    for (let line = 0; line < 250; line++) { ring.append(`line ${line}\n`, false); }
    assert.equal(ring.lineCount(), 100, 'the ring keeps only the newest lines');
    assert.match(ring.text(false), /^line 150\n/);
    console.log('  ✓ RTT endpoint, CSP, log name and scrollback ring');

    const monitor = new RttMonitorViewProvider({ fsPath: root }, root, () => 'Demo Pair');
    const bridge0 = await fakeBridge(); servers.push(bridge0);
    monitor.attach('cr8_0', bridge0.endpoint);
    await until(() => monitor.stateOf('cr8_0').state === 'connected', 'R8-0 connect');
    bridge0.write('NuttShell (NSH)\r\nnsh> ');
    await until(() => monitor.bufferText('cr8_0').includes('nsh> '), 'R8-0 data');
    assert.equal(monitor.send('ps'), true);
    await until(() => bridge0.received.join('') === 'ps\r\n', 'input with CRLF');
    config.set('lineEnding', 'lf');
    monitor.send('free');
    await until(() => bridge0.received.join('').endsWith('free\n'), 'input with LF');
    console.log('  ✓ monitor shows bridge output and sends input with the configured line ending');

    monitor.detach('switching');
    const bridge1 = await fakeBridge(); servers.push(bridge1);
    monitor.attach('cr8_1', bridge1.endpoint);
    await until(() => monitor.stateOf('cr8_1').state === 'connected', 'R8-1 connect');
    bridge1.write('R8-1 io ready\n');
    await until(() => monitor.bufferText('cr8_1').includes('R8-1 io ready'), 'R8-1 data');
    assert.ok(!monitor.bufferText('cr8_0').includes('R8-1'), 'cores keep separate traces');
    assert.ok(!monitor.bufferText('cr8_1').includes('NuttShell'), 'cores keep separate traces');
    assert.equal(monitor.stateOf('cr8_0').state, 'switching');
    const saved = await monitor.saveLog();
    assert.equal(path.dirname(saved), path.join(root, 'logs', 'rtt'));
    assert.match(path.basename(saved), /^demo-pair-cr8_1-\d{6}-\d{6}\.log$/);
    assert.match(fs.readFileSync(saved, 'utf8'), /\d\d:\d\d:\d\d\.\d{3} +R8-1 io ready/);
    await monitor.copy();
    assert.ok(clipboard.includes('R8-1 io ready'));
    console.log('  ✓ switching cores keeps per-core buffers; Save Log writes logs/rtt/<setup>-<core>-<time>.log');

    monitor.detach('stopped');
    const busy = await fakeBridge('close'); servers.push(busy);
    monitor.attach('cr8_0', busy.endpoint);
    await until(() => monitor.stateOf('cr8_0').state === 'failed', 'busy port');
    assert.match(monitor.stateOf('cr8_0').detail, /port busy/);
    monitor.detach('stopped');
    const closed = await fakeBridge(); const refused = closed.endpoint; await closed.close();
    monitor.attach('cr8_0', refused);
    await until(() => monitor.stateOf('cr8_0').state === 'failed', 'refused port');
    assert.match(monitor.stateOf('cr8_0').detail, /not listening/);
    monitor.detach('stopped');
    console.log('  ✓ a busy or closed bridge port fails visibly with no reconnect loop');

    // Trace session against a fake backend and sink.
    const log = [];
    const sink = { cores: new Map(), states: [], layout: undefined,
      get core() { return this.attachedCore(); },
      attach(core, endpoint, source = 'rtt') { this.cores.set(core, source); log.push(`attach ${core} ${endpoint}${source === 'serial' ? ' serial' : ''}`); },
      detach(state, detail, source = 'rtt') {
        if (state !== 'paused') { for (const [core, from] of this.cores) { if (source === 'all' || from === source) { this.cores.delete(core); } } }
        this.states.push([state, detail, source]);
      },
      fail(core, detail) { this.cores.delete(core); this.states.push(['failed', detail]); },
      attachedCores(source) { return [...this.cores].filter(([, from]) => !source || from === source).map(([core]) => core); },
      attachedCore() { return this.attachedCores('rtt')[0]; }, setLayout(layout) { this.layout = layout; }, reveal: async () => {} };
    const listeners = [];
    const backend = { setup: 'one', debug: false, failNext: false,
      startBridge: async (target, owner) => {
        log.push(`start ${target}${owner ? ' owned' : ''}`);
        if (backend.failNext) { backend.failNext = false; return { ok: false, message: 'J-Link connect failed' }; }
        const all = { cr8_0: '127.0.0.1:19021', cr8_1: '127.0.0.1:19031' };
        return { ok: true, endpoints: target === 'dual' ? all : { [target]: all[target] } };
      },
      startSerial: async (core) => {
        log.push(`serial ${core}`);
        if (backend.serialFails) { return { ok: false, message: 'the UART is held by another console' }; }
        const relay = { ok: true, endpoint: '127.0.0.1:19042', stop: () => { log.push(`serial stop ${core}`); }, onExit: (listener) => { backend.serialExit = listener; } };
        return relay;
      },
      stopBridge: async () => { log.push('stop'); return true; },
      setupId: () => backend.setup, debugActive: () => backend.debug,
      onSessionChange: (listener) => { listeners.push(listener); return { dispose: () => listeners.splice(listeners.indexOf(listener), 1) }; },
      recoverBoth: async () => { log.push('recover'); } };
    const trace = new RttTraceSession(backend, sink);
    assert.equal(defaultTraceCore((core) => (core === 'cr8_1' ? 'rtt' : 'serial')), 'cr8_1');
    assert.equal(defaultTraceCore(() => 'serial'), undefined);

    assert.equal(await trace.start('cr8_0'), true);
    const owner = Symbol('workflow');
    log.length = 0;
    assert.equal(await trace.pauseFor('Load', async () => { log.push('load'); return true; }, (ok) => ok, false, owner), true);
    assert.deepEqual(log, ['stop', 'load', 'start cr8_0 owned', 'attach cr8_0 127.0.0.1:19021'], 'load runs between stop and resume');

    log.length = 0;
    await trace.pauseFor('Load', async () => { log.push('load'); return false; }, (ok) => ok);
    assert.deepEqual(log, ['stop', 'load'], 'a failed load never resumes the bridge');
    assert.equal(trace.tracedCore(), undefined);
    assert.match(sink.states.at(-1)[1], /not resumed: Load did not complete/);

    await trace.start('cr8_0'); log.length = 0;
    await assert.rejects(trace.pauseFor('Recover', async () => { throw new Error('probe lost'); }, () => true), /probe lost/);
    assert.deepEqual(log, ['stop'], 'a throwing job never resumes the bridge');

    await trace.start('cr8_0'); log.length = 0;
    assert.equal(await trace.switchTo('cr8_1'), true);
    assert.deepEqual(log, ['stop', 'start cr8_1', 'attach cr8_1 127.0.0.1:19031'], 'switching stops the old bridge before the new one');
    log.length = 0;
    assert.equal(await trace.switchTo('cr8_1'), true);
    assert.deepEqual(log, [], 'switching to the traced core is a no-op');

    log.length = 0;
    await trace.pauseFor('Load', async () => { await trace.stop(); return true; }, (ok) => ok);
    assert.deepEqual(log, ['stop', 'stop'], 'Stop Sessions during a job cancels the resume');

    await trace.start('cr8_0'); log.length = 0;
    await trace.pauseFor('Load', async () => { backend.setup = 'two'; return true; }, (ok) => ok);
    assert.deepEqual(log, ['stop'], 'a changed setup is not resumed');
    assert.match(sink.states.at(-1)[1], /setup changed/);

    await trace.start('cr8_1'); log.length = 0;
    backend.debug = true;
    await trace.pauseFor('Debug', async () => true, (ok) => ok, true);
    assert.deepEqual(log, ['stop'], 'debug keeps the bridge paused');
    listeners.forEach((listener) => listener());
    await tick();
    assert.deepEqual(log, ['stop'], 'still paused while the debug session holds the probe');
    backend.debug = false;
    [...listeners].forEach((listener) => listener());
    await until(() => log.length === 3, 'resume after debug');
    assert.deepEqual(log, ['stop', 'start cr8_1', 'attach cr8_1 127.0.0.1:19031'], 'the bridge resumes when the debug session ends');
    assert.equal(listeners.length, 0, 'the debug wait unsubscribes');

    log.length = 0; errors.length = 0;
    backend.failNext = true;
    await trace.pauseFor('Load', async () => true, (ok) => ok);
    assert.deepEqual(log, ['stop', 'start cr8_1'], 'a failed bridge start is tried once only');
    assert.equal(trace.tracedCore(), undefined);
    assert.equal(sink.states.at(-1)[0], 'failed');
    assert.match(errors.at(-1), /not retried/);
    log.length = 0;
    await trace.pauseFor('Load', async () => true, (ok) => ok);
    assert.deepEqual(log, [], 'after a failed start nothing is paused or resumed');
    trace.dispose();
    console.log('  ✓ trace session pauses for probe jobs, resumes only on success, never retries a failed start');

    // Dual bridge: both cores attach in the split layout and pause/resume together.
    const dual = new RttTraceSession(backend, sink);
    backend.setup = 'one'; log.length = 0;
    assert.equal(await dual.start('dual'), true);
    assert.equal(sink.layout, 'split');
    assert.deepEqual(log, ['start dual', 'attach cr8_0 127.0.0.1:19021', 'attach cr8_1 127.0.0.1:19031']);
    assert.equal(dual.dualActive(), true); assert.equal(dual.tracedCore(), undefined); assert.equal(dual.attachedAll(), true);
    log.length = 0;
    assert.equal(await dual.switchTo('cr8_1'), true);
    assert.deepEqual(log, [], 'the core switch never restarts a dual trace');
    await dual.pauseFor('Load', async () => { log.push('load'); return true; }, (ok) => ok);
    assert.deepEqual(log, ['stop', 'load', 'start dual', 'attach cr8_0 127.0.0.1:19021', 'attach cr8_1 127.0.0.1:19031'],
      'a load pauses both panes and resumes the one dual bridge');
    log.length = 0; backend.failNext = true;
    await dual.pauseFor('Load', async () => true, (ok) => ok);
    assert.deepEqual(sink.states.slice(-2).map(([state]) => state), ['failed', 'failed'], 'a failed dual start fails both panes');
    assert.equal(dual.dualActive(), false);
    await dual.stop(); dual.dispose();

    // Mixed setup: one RTT core plus a serial pane; the serial relay survives probe jobs.
    const mixed = new RttTraceSession(backend, sink);
    log.length = 0;
    assert.equal(await mixed.start({ rtt: 'cr8_0', serial: 'cr8_1' }), true);
    assert.equal(sink.layout, 'split');
    assert.deepEqual(log, ['serial cr8_1', 'attach cr8_1 127.0.0.1:19042 serial', 'start cr8_0', 'attach cr8_0 127.0.0.1:19021']);
    log.length = 0;
    await mixed.pauseFor('Load', async () => { log.push('load'); return true; }, (ok) => ok);
    assert.deepEqual(log, ['stop', 'load', 'start cr8_0', 'attach cr8_0 127.0.0.1:19021'], 'only the RTT pane pauses');
    assert.deepEqual(sink.attachedCores('serial'), ['cr8_1'], 'the serial pane stays connected through a load');
    log.length = 0;
    await mixed.pauseFor('Load', async () => false, (ok) => ok);
    assert.deepEqual(mixed.tracedPlan(), { rtt: undefined, serial: 'cr8_1' }, 'a failed load drops RTT and keeps the serial wish');
    backend.serialExit();
    assert.equal(sink.states.at(-1)[0], 'failed', 'a relay that exits fails its pane');
    assert.equal(mixed.tracedPlan(), undefined);
    await mixed.start({ serial: 'cr8_1' }); log.length = 0;
    assert.equal(sink.layout, 'single');
    assert.equal(await mixed.stop(), true);
    assert.deepEqual(log, ['serial stop cr8_1', 'stop'], 'Stop ends the serial relay too');
    backend.serialFails = true; errors.length = 0;
    assert.equal(await mixed.start({ serial: 'cr8_1' }), false);
    assert.match(errors.at(-1), /held by another console/);
    log.length = 0;
    assert.equal(await mixed.start({ rtt: 'cr8_0', serial: 'cr8_1' }), false);
    assert.deepEqual(log, ['serial cr8_1', 'start cr8_0', 'attach cr8_0 127.0.0.1:19021'], 'a refused UART still traces the RTT core');
    await mixed.stop();
    backend.serialFails = false; mixed.dispose();

    assert.deepEqual(resolveTracePlan(() => 'rtt', 'dual'), { rtt: 'dual' });
    assert.deepEqual(resolveTracePlan(() => 'rtt', 'switch', 'cr8_1'), { rtt: 'cr8_1' });
    assert.deepEqual(resolveTracePlan((core) => (core === 'cr8_0' ? 'rtt' : 'sci5'), 'dual'), { rtt: 'cr8_0', serial: 'cr8_1' });
    assert.deepEqual(resolveTracePlan(() => 'scif0', 'dual', 'cr8_1'), { serial: 'cr8_1' });
    assert.equal(resolveTracePlan(() => 'none', 'dual'), undefined);
    console.log('  ✓ dual bridge and serial relay panes: split layout, joint pause, serial survives probe jobs');

    // Split panes route input per core and count bridge drop reports.
    const split = new RttMonitorViewProvider({ fsPath: root }, root, () => 'Demo Pair');
    const left = await fakeBridge(); const right = await fakeBridge(); servers.push(left, right);
    split.setLayout('split');
    split.attach('cr8_0', left.endpoint); split.attach('cr8_1', right.endpoint);
    await until(() => split.stateOf('cr8_0').state === 'connected' && split.stateOf('cr8_1').state === 'connected', 'both panes connect');
    config.set('lineEnding', 'crlf');
    assert.equal(split.send('top', 'cr8_1'), true);
    await until(() => right.received.join('') === 'top\r\n', 'R8-1 input');
    assert.deepEqual(left.received, [], 'input for R8-1 never reaches R8-0');
    right.write('a\r\n<<rtt-bridge: output dropped: 120 B>>\r\nb\r\n<<rtt-bridge: output dropped: 8 B>>\r\n');
    await until(() => split.stateOf('cr8_1').dropped === 128, 'drop count');
    assert.equal(split.stateOf('cr8_0').dropped, 0);
    split.detach('stopped', undefined, 'all');
    split.dispose();
    console.log('  ✓ split panes route input per core and count dropped RTT output');
    monitor.dispose();
  } finally {
    Module._load = originalLoad;
    for (const server of servers) { await server.close(); }
    fs.rmSync(root, { recursive: true, force: true });
  }
}

module.exports = runRttMonitorTests;
