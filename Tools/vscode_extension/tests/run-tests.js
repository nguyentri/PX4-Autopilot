// Standalone extension integration unit tests
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const Module = require('module');
const os = require('os');
const esbuild = require(path.join(__dirname, '..', 'node_modules', 'esbuild'));

const EXT_DIR = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(EXT_DIR, '../..');

console.log('== Running VS Code Extension Unit Tests ==');

// Test 1: Verify dist/extension.js was built and is non-empty
const distFile = path.join(EXT_DIR, 'dist', 'extension.js');
assert.ok(fs.existsSync(distFile), 'dist/extension.js must exist');
const distStats = fs.statSync(distFile);
assert.ok(distStats.size > 1000, `dist/extension.js must be > 1KB (got ${distStats.size} bytes)`);
console.log('  ✓ dist/extension.js exists and is bundled');

// Test 2: Verify package.json manifests and contributes
const pkg = JSON.parse(fs.readFileSync(path.join(EXT_DIR, 'package.json'), 'utf-8'));
assert.strictEqual(pkg.name, 'px4-nuttx-firmware-workspace');
assert.strictEqual(pkg.license, 'BSD-3-Clause');
assert.ok(pkg.contributes.views['px4-nuttx-workspace'].length >= 4, 'Must define 4 views');
assert.ok(pkg.contributes.commands.length >= 8, 'Must contribute commands');
assert.ok(pkg.contributes.jsonValidation.length >= 3, 'Must contribute schema validations');
console.log('  ✓ package.json contributes all required views, commands, and schemas');

// Test 3: Verify all schemas exist and parse
for (const jv of pkg.contributes.jsonValidation) {
  const schemaPath = path.join(EXT_DIR, jv.url);
  assert.ok(fs.existsSync(schemaPath), `Schema ${jv.url} must exist at ${schemaPath}`);
  const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf-8'));
  assert.strictEqual(schema.$schema, 'http://json-schema.org/draft-07/schema#');
}
console.log('  ✓ all contributed JSON schemas exist and are valid JSON');

// Test 4: Verify default devices.json and groups.json exist
const devPath = path.join(EXT_DIR, 'profiles', 'devices.json');
const grpPath = path.join(EXT_DIR, 'profiles', 'groups.json');
assert.ok(fs.existsSync(devPath), 'profiles/devices.json must exist');
assert.ok(fs.existsSync(grpPath), 'profiles/groups.json must exist');
const devs = JSON.parse(fs.readFileSync(devPath, 'utf-8'));
assert.ok(devs.boards['rdk-rzv2h'], 'rdk-rzv2h must be defined in devices.json');
assert.ok(devs.boards['evk-ra8p1'], 'evk-ra8p1 must be defined in devices.json');
assert.ok(devs.boards['fpb-ra8e1'], 'fpb-ra8e1 must be defined in devices.json');
console.log('  ✓ devices.json and groups.json contain all supported Renesas platforms');

// Test 5: Verify packaged VSIX exists
const vsixFile = path.join(EXT_DIR, 'px4-nuttx-firmware-workspace-0.1.0.vsix');
assert.ok(fs.existsSync(vsixFile), 'VSIX package must be present');
const vsixStats = fs.statSync(vsixFile);
assert.ok(vsixStats.size > 5000, `VSIX package must be > 5KB (got ${vsixStats.size} bytes)`);
console.log('  ✓ packaged VSIX exists and is valid');

async function runBehavioralTests() {
  const registered = new Map();
  class EventEmitter {
    constructor() {
      this.listeners = [];
      this.event = (listener) => {
        this.listeners.push(listener);
        return { dispose: () => { this.listeners = this.listeners.filter((item) => item !== listener); } };
      };
    }
    fire(value) { for (const listener of this.listeners) listener(value); }
    dispose() { this.listeners = []; }
  }
  class TreeItem { constructor(label, collapsibleState) { this.label = label; this.collapsibleState = collapsibleState; } }
  class ThemeIcon { constructor(id, color) { this.id = id; this.color = color; } }
  class Task { constructor(definition, scope, name, source, execution) { Object.assign(this, { definition, scope, name, source, execution }); } }
  class ProcessExecution { constructor(process, args, options) { Object.assign(this, { process, args, options }); } }
  class ShellExecution { constructor(commandLine, options) { Object.assign(this, { commandLine, options }); } }
  const workspace = {
    isTrusted: false,
    workspaceFolders: [{ uri: { fsPath: REPO_ROOT }, name: 'PX4-Autopilot' }],
    getConfiguration: () => ({ get: (_, fallback) => fallback }),
  };
  const debugStarted = new EventEmitter();
  const debugTerminated = new EventEmitter();
  let lastDebugSession;
  const vscode = {
    EventEmitter,
    TreeItem,
    ThemeIcon,
    ThemeColor: ThemeIcon,
    Task,
    ProcessExecution,
    ShellExecution,
    Disposable: class {},
    TreeItemCollapsibleState: { None: 0 },
    QuickPickItemKind: { Separator: -1 },
    TaskScope: { Workspace: 2 },
    TaskGroup: { Build: {} },
    ProgressLocation: { Notification: 1 },
    workspace,
    window: {
      showInformationMessage: async () => undefined,
      showErrorMessage: async () => undefined,
      showWarningMessage: async () => undefined,
      showInputBox: async () => undefined,
      showQuickPick: async () => undefined,
      withProgress: async (_, callback) => callback({ report: () => {} }, { isCancellationRequested: false }),
    },
    commands: {
      registerCommand: (id, callback) => { registered.set(id, callback); return { dispose: () => registered.delete(id) }; },
      executeCommand: async (id, ...args) => registered.get(id)?.(...args),
    },
    Uri: { file: (value) => ({ fsPath: value, toString: () => value }), parse: (value) => value },
    debug: {
      onDidStartDebugSession: (listener) => debugStarted.event(listener),
      onDidTerminateDebugSession: (listener) => debugTerminated.event(listener),
      startDebugging: async (_folder, configuration) => {
        lastDebugSession = { id: `managed-${Date.now()}`, configuration };
        debugStarted.fire(lastDebugSession);
        return true;
      },
      stopDebugging: async (session) => {
        debugTerminated.fire(session);
        return true;
      },
    },
  };
  const originalLoad = Module._load;
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'px4-extension-behavior-'));
  const sourceModule = (name) => {
    const input = path.join(EXT_DIR, 'src', `${name}.ts`);
    const output = esbuild.buildSync({
      entryPoints: [input],
      bundle: true,
      platform: 'node',
      format: 'cjs',
      external: ['vscode'],
      write: false,
    }).outputFiles[0].text;
    const filename = path.join(temporary, `${name.replaceAll('/', '-')}.cjs`);
    const module = new Module(filename, require.main);
    module.filename = filename;
    module.paths = Module._nodeModulePaths(path.dirname(input));
    module._compile(output, filename);
    return module.exports;
  };
  Module._load = function(request, parent, isMain) {
    return request === 'vscode' ? vscode : originalLoad.call(this, request, parent, isMain);
  };

  try {
    const { BackendClient, ProbeLeaseManager, WorkspaceTrustError } = sourceModule('backend-client');
    let trustRejected = false;
    try {
      await new BackendClient(REPO_ROOT).executeCommand('doctor');
    } catch (error) {
      trustRejected = error instanceof WorkspaceTrustError;
    }
    assert.strictEqual(trustRejected, true, 'untrusted backend execution must be rejected before spawning');
    console.log('  ✓ workspace trust blocks backend process execution');

    const { OperationsViewProvider } = sourceModule('views/operations-view');
    const { ReadinessViewProvider } = sourceModule('views/readiness-view');
    const restrictedOperations = await new OperationsViewProvider().getChildren();
    const restrictedReadiness = await new ReadinessViewProvider({
      runDoctor: async () => { throw new Error('Restricted Mode must not invoke Doctor'); },
    }).getChildren();
    assert.strictEqual(restrictedOperations[0].label, 'Workspace Trust Required');
    assert.strictEqual(restrictedReadiness[0].label, 'Workspace Trust Required');
    console.log('  ✓ Restricted Mode renders static trust guidance without running backend views');

    workspace.isTrusted = true;
    const device = (core, buildAvailable, loadAvailable, debugAvailable) => ({
      core,
      jlinkDevice: core,
      buildAvailable,
      loadAvailable,
      debugAvailable,
      qualification: 'build-clean',
      supportedFamilies: ['px4', 'nuttx'],
      remediation: null,
      reasons: [],
    });
    const catalog = {
      px4Targets: Array.from({ length: 16 }, (_, index) => index === 0
        ? { target: 'renesas_fpb-ra8e1_default', board: 'fpb-ra8e1', core: 'cm85', family: 'px4', file: 'x' }
        : { target: `renesas_rdk-rzv2h_sample_${index}`, board: 'rdk-rzv2h', core: 'cr8_0', family: 'px4', file: 'x' }),
      nuttxConfigs: {
        'rdk-rzv2h': Array.from({ length: 128 }, (_, index) => ({ config: `cfg-${index}`, board: 'rdk-rzv2h', core: 'cr8_0', family: 'nuttx', directory: 'x' })),
        'evk-ra8p1': Array.from({ length: 30 }, (_, index) => ({ config: `ra-${index}`, board: 'evk-ra8p1', core: 'cm85', family: 'nuttx', directory: 'x' })),
      },
      devices: {
        'rdk-rzv2h': { id: 'rdk-rzv2h', name: 'RZ', soc: 'RZ', cores: { cr8_0: device('cr8_0', true, true, true) } },
        'evk-ra8p1': { id: 'evk-ra8p1', name: 'RA', soc: 'RA', cores: { cm85: device('cm85', true, false, true) } },
        'fpb-ra8e1': { id: 'fpb-ra8e1', name: 'RAE', soc: 'RAE', cores: { cm85: device('cm85', true, false, false) } },
      },
      groups: {},
      counts: { px4: 16, rzv2hNuttx: 128, ra8p1Nuttx: 30 },
    };
    const { registerSelectionCommands } = sourceModule('commands-selection');
    const selectionContext = { subscriptions: [] };
    let offered = [];
    vscode.window.showQuickPick = async (items) => { offered = items; return undefined; };
    const selectionStore = {
      setCatalog: () => {},
      setSelection: async () => {},
      getGroupMembers: () => [],
      getConsoleTransport: () => 'rtt',
      getWorkspaceRoot: () => REPO_ROOT,
    };
    registerSelectionCommands(selectionContext, { getCatalog: async () => ({ status: 'ok', data: catalog }) }, selectionStore, { refresh: () => {} }, { refresh: () => {} });
    await registered.get('px4Nuttx.selectProfile')();
    assert.strictEqual(offered.filter((item) => item.selection?.build.family === 'nuttx' && item.selection.board === 'rdk-rzv2h').length, 128);
    assert.strictEqual(offered.filter((item) => item.selection?.build.family === 'nuttx' && item.selection.board === 'evk-ra8p1').length, 30);
    assert.strictEqual(offered.filter((item) => item.selection?.build.family === 'px4').length, 16);
    console.log('  ✓ profile picker exposes the complete RZ/V2H and RA8P1 catalogs');

    const raItem = offered.find((item) => item.selection?.board === 'fpb-ra8e1');
    assert.ok(raItem, 'RA8E1 PX4 target should be offered');
    assert.strictEqual(raItem.selection.load, undefined, 'build-only target must not advertise load');
    assert.strictEqual(raItem.selection.debug, undefined, 'build-only target must not advertise debug');
    console.log('  ✓ build-only targets remain selectable without optional load/debug gates');

    const refreshed = { selection: 0, readiness: 0, artifacts: 0, operations: 0 };
    const refreshContext = { subscriptions: [] };
    const refreshStore = { ...selectionStore, setCatalog: () => { refreshed.selection += 1; } };
    const refreshClient = {
      getCatalog: async () => ({ status: 'ok', data: catalog }),
      runDoctor: async () => ({ status: 'ok', data: { tools: {}, probes: [], environment: { leakedToolchainVars: [] }, submodules: { nuttxInitialized: true } } }),
    };
    registerSelectionCommands(
      refreshContext,
      refreshClient,
      refreshStore,
      { refresh: () => { refreshed.selection += 1; } },
      { refresh: () => { refreshed.readiness += 1; }, setDoctorData: async () => { refreshed.readiness += 1; } },
      { refresh: () => { refreshed.artifacts += 1; } },
      { refresh: () => { refreshed.operations += 1; } }
    );
    await registered.get('px4Nuttx.refresh')();
    assert.ok(refreshed.selection >= 2 && refreshed.readiness >= 2 && refreshed.artifacts >= 2 && refreshed.operations >= 2, 'Refresh must update all four views before and after backend state refresh');
    console.log('  ✓ refresh invalidates all four native views and reloads catalog/doctor state');

    const { registerExecutionCommands } = sourceModule('commands-execution');
    const selection = { schemaVersion: 1, id: 'a', board: 'rdk-rzv2h', core: 'cr8_0', build: { family: 'px4', target: 'x', mode: 'incremental' } };
    let currentSelection = selection;
    let attached = 0;
    let loadCalls = 0;
    let loadedLease, attachedLease;
    let loadOutcome = { status: 'blocked', data: { recoveryRequired: true }, diagnostics: [{ message: 'blocked' }] };
    const executionStore = {
      getSelection: () => currentSelection,
      getSelectedProbe: () => 'probe',
      getSelectedCore: () => 'cr8_0',
      getReceiptPath: (value) => value.id === selection.id ? 'receipt-a.json' : null,
      readReceipt: () => ({ artifacts: [{ core: 'cr8_0', rttAddress: '0x081a2400' }] }),
      getWorkspaceRoot: () => REPO_ROOT,
      ensureSelectionFileOnDisk: () => path.join(temporary, 'selection.json'),
      writeSelectionSnapshot: () => path.join(temporary, 'selection.json'),
      setReceiptPath: () => {},
      getConsoleTransport: () => 'rtt',
    };
    const executionClient = {
      probeLeases: {
        acquire: async (serial) => ({ lease: { leaseToken: 'execution-lease', serial }, release: async () => {} }),
      },
      loadTarget: async (...args) => { loadCalls += 1; loadedLease = args[3].lease; return loadOutcome; },
      buildSelection: async () => ({ status: 'ok', data: {}, diagnostics: [], receiptPath: 'receipt-a.json' }),
    };
    const executionController = registerExecutionCommands(selectionContext, executionClient, executionStore, {
      startManagedAttach: async (...args) => { attached += 1; attachedLease = args[4]; return true; },
      setConsoleHandoff: () => {},
    }, { refresh: () => {} });
    await registered.get('px4Nuttx.loadAndDebug')();
    assert.strictEqual(attached, 0, 'blocked load must not attach the debugger');
    const callsBeforeSwitch = loadCalls;
    currentSelection = { ...selection, id: 'b' };
    await registered.get('px4Nuttx.load')();
    assert.strictEqual(attached, 0, 'receipt binding must invalidate when selection changes');
    assert.strictEqual(loadCalls, callsBeforeSwitch, 'stale profile receipt must not invoke loader');
    currentSelection = selection;
    loadOutcome = { status: 'failed', data: {}, diagnostics: [{ message: 'failed' }] };
    await registered.get('px4Nuttx.loadAndDebug')();
    loadOutcome = { status: 'cancelled', data: {}, diagnostics: [{ message: 'cancelled' }] };
    await registered.get('px4Nuttx.loadAndDebug')();
    assert.strictEqual(attached, 0, 'failed and cancelled loads must never attach the debugger');
    loadOutcome = { status: 'ok', data: { status: 'verified' }, diagnostics: [] };
    assert.strictEqual(await registered.get('px4Nuttx.loadAndDebug')(), true);
    assert.strictEqual(attached, 1);
    assert.deepStrictEqual(attachedLease.lease, loadedLease, 'verified load and attach must transfer one reservation');
    console.log('  ✓ failed/blocked/cancelled composites never attach; successful composite retains one probe lease');
    let stopFails = true;
    executionClient.consoleAction = async (action) => action === 'stop' && stopFails
      ? { status: 'failed', data: {}, diagnostics: [{ message: 'fixture stop failed' }] }
      : { status: 'ok', data: { running: action === 'start' }, diagnostics: [] };
    assert.strictEqual(await registered.get('px4Nuttx.startConsole')(), true);
    assert.strictEqual(await registered.get('px4Nuttx.stopConsole')(), false);
    assert.strictEqual((await executionController.stopConsoleForHandoff()).ok, false, 'stop failure must retain active ownership');
    stopFails = false;
    assert.strictEqual(await registered.get('px4Nuttx.stopConsole')(), true);
    console.log('  ✓ console stop failure keeps ownership and prevents debug handoff');
    const normalReceiptLookup = executionStore.getReceiptPath;
    executionStore.getReceiptPath = () => null;
    executionClient.buildSelection = async () => {
      currentSelection = { ...selection, id: 'changed-during-build' };
      return { status: 'ok', data: {}, diagnostics: [], receiptPath: 'receipt-a.json' };
    };
    const callsBeforeBuildSwitch = loadCalls;
    assert.strictEqual(await registered.get('px4Nuttx.loadAndDebug')(), false);
    assert.strictEqual(loadCalls, callsBeforeBuildSwitch, 'selection change during build must not retarget a composite operation');
    executionStore.getReceiptPath = normalReceiptLookup;
    currentSelection = selection;


    const { Px4NuttxTaskProvider } = sourceModule('task-provider');
    const taskStore = {
      getSelection: () => selection,
      writeSelectionSnapshot: () => path.join(temporary, 'selection.json'),
      ensureSelectionFileOnDisk: () => path.join(temporary, 'selection.json'),
    };
    const tasks = new Px4NuttxTaskProvider(REPO_ROOT, taskStore).provideTasks();
    assert.strictEqual(tasks.length, 3, 'only admitted Build/Clean/Doctor tasks should be contributed');
    assert.ok(tasks.every((task) => task.scope === workspace.workspaceFolders[0]), 'tasks must be scoped to the owning workspace folder');
    assert.notDeepStrictEqual(tasks[0].execution.args, tasks[1].execution.args);
    assert.ok(tasks[1].execution.args.includes('--clean'), 'clean rebuild task must pass additive --clean');
    console.log('  ✓ clean rebuild tasks use immutable snapshots and explicit --clean');

    currentSelection = selection;
    let leaseReleases = 0;
    const { Px4NuttxDebugProvider } = sourceModule('debug-provider');
    const debugProvider = new Px4NuttxDebugProvider(
      {
        probeLeases: {
          acquire: async (serial) => ({
            lease: { leaseToken: 'debug-lease', serial },
            release: async () => { leaseReleases += 1; },
            sendEvent: () => {},
          }),
        },
        getDebugConfig: async () => ({ status: 'ok', data: { configuration: { type: 'cortex-debug' } }, diagnostics: [] }),
      },
      executionStore
    );
    const debugContext = { subscriptions: [] };
    debugProvider.registerLifecycle(debugContext);
    assert.strictEqual(await debugProvider.startManagedAttach('receipt-a.json', 'cr8_0', selection, 'probe'), true);
    assert.strictEqual(leaseReleases, 0, 'managed debug lease must survive startup until the exact session terminates');
    debugTerminated.fire(lastDebugSession);
    await new Promise((resolve) => setImmediate(resolve));
    assert.strictEqual(leaseReleases, 1, 'exact managed debug termination must release its lease');
    debugTerminated.fire({ id: 'unrelated', configuration: {} });
    assert.strictEqual(leaseReleases, 1, 'unrelated debug sessions must not release managed leases');
    await debugProvider.disposeAsync();
    console.log('  ✓ managed debug ownership follows exact session lifecycle');

    const fakeBackendRoot = path.join(temporary, 'backend-fixture');
    fs.mkdirSync(path.join(fakeBackendRoot, 'Tools'), { recursive: true });
    fs.writeFileSync(path.join(fakeBackendRoot, 'Tools', 'firmware-workspace.py'), [
      'import json, os, sys, time',
      'command = sys.argv[1]',
      'if command == "probe-session":',
      '    serial = sys.argv[sys.argv.index("--serial") + 1]',
      '    print(json.dumps({"status":"ok","data":{"leaseToken":"lease-fixture","serial":serial}}), flush=True)',
      '    sys.stdin.read()',
      '    raise SystemExit(0)',
      'if command == "slow":',
      '    print("live-fixture", file=sys.stderr, flush=True)',
      '    time.sleep(5)',
      'if command == "should-not-run":',
      '    open(os.path.join(os.path.dirname(__file__), "spawn-marker"), "w").write("spawned")',
      'print(json.dumps({"protocolVersion":1,"operationId":command,"status":"ok","data":{"lease":os.environ.get("FIRMWARE_PROBE_LEASE"),"serial":os.environ.get("FIRMWARE_PROBE_SERIAL")},"diagnostics":[],"childExitCode":0,"receiptPath":None}), flush=True)',
    ].join('\n'));
    const fixtureClient = new BackendClient(fakeBackendRoot);
    const immediateCancellation = await fixtureClient.executeCommand('should-not-run', [], {
      cancellationToken: { isCancellationRequested: true, onCancellationRequested: () => ({ dispose: () => {} }) },
    });
    assert.strictEqual(immediateCancellation.status, 'cancelled');
    assert.ok(!fs.existsSync(path.join(fakeBackendRoot, 'Tools', 'spawn-marker')), 'already-cancelled command must not spawn a child');
    const streamed = [];
    const leasedResult = await fixtureClient.executeCommand('load', [], {
      lease: { leaseToken: 'lease-fixture', serial: 'serial-fixture' },
      onOutput: (chunk, stream) => streamed.push({ chunk, stream }),
    });
    assert.strictEqual(leasedResult.data.lease, 'lease-fixture');
    assert.strictEqual(leasedResult.data.serial, 'serial-fixture');
    assert.ok(streamed.some((item) => item.stream === 'stdout'));
    const probe = await fixtureClient.startProbeSession('serial-fixture');
    assert.strictEqual(probe.lease.serial, 'serial-fixture');
    await probe.release();
    let sessionStarts = 0;
    const managedSession = {
      lease: { leaseToken: 'manager-lease', serial: 'serial-manager' },
      isReleased: () => false,
      release: async () => {},
      sendEvent: () => {},
    };
    const leaseManager = new ProbeLeaseManager({ startProbeSession: async () => { sessionStarts += 1; return managedSession; } });
    const managerHandle = await leaseManager.acquire('serial-manager');
    await assert.rejects(leaseManager.acquire('serial-manager'), /already reserved/);
    await managerHandle.release();
    assert.strictEqual(sessionStarts, 1, 'generic acquisition must not share an active reservation');
    const cancellationListeners = [];
    const cancellationResultPromise = fixtureClient.executeCommand('slow', [], {
      cancellationToken: { onCancellationRequested: (listener) => { cancellationListeners.push(listener); return { dispose: () => {} }; } },
      onOutput: (chunk, stream) => streamed.push({ chunk, stream }),
    });
    setTimeout(() => cancellationListeners.forEach((listener) => listener()), 100);
    const cancellationResult = await cancellationResultPromise;
    assert.strictEqual(cancellationResult.status, 'cancelled');
    assert.ok(streamed.some((item) => item.chunk.includes('live-fixture')), 'stderr must stream before cancellation');
    fixtureClient.dispose();
    console.log('  ✓ backend child output, cancellation, probe lease startup and lease env are behavioral');

    const { SelectionStore } = sourceModule('selection-store');
    const persistentState = new Map();
    const extensionContext = {
      workspaceState: {
        get: (key, fallback) => persistentState.has(key) ? persistentState.get(key) : fallback,
        update: async (key, value) => { persistentState.set(key, value); },
      },
    };
    const receiptPath = path.join(fakeBackendRoot, 'receipt.json');
    fs.writeFileSync(receiptPath, JSON.stringify({
      schemaVersion: 1,
      receiptId: 'receipt-a',
      timestamp: 'now',
      family: 'px4',
      board: 'rdk-rzv2h',
      core: 'cr8_0',
      selectionId: 'a',
      target: 'x',
      gitRevision: 'fixture',
      gitDirty: false,
      compiler: 'fixture',
      artifacts: [{ path: 'fixture.elf', sha256: 'a'.repeat(64), size: 1, core: 'cr8_0' }],
      status: 'committed',
    }));
    const persistentStore = new SelectionStore(extensionContext, fakeBackendRoot);
    await persistentStore.setSelection(selection);
    assert.deepStrictEqual(
      JSON.parse(fs.readFileSync(path.join(fakeBackendRoot, '.vscode', 'active-selection.json'), 'utf8')),
      selection,
      'trusted profile selection must publish the active-selection projection'
    );
    persistentStore.setReceiptPath('receipt.json', selection);
    assert.strictEqual(persistentStore.getReceiptPath(selection), 'receipt.json');
    const restoredStore = new SelectionStore(extensionContext, fakeBackendRoot);
    assert.strictEqual(restoredStore.getReceiptPath(selection), 'receipt.json');
    const snapshotPath = restoredStore.writeSelectionSnapshot(selection);
    fs.writeFileSync(snapshotPath, JSON.stringify({ ...selection, id: 'tampered' }));
    assert.throws(() => restoredStore.writeSelectionSnapshot(selection), /modified after publication/);
    fs.writeFileSync(receiptPath, JSON.stringify({
      schemaVersion: 1,
      receiptId: 'receipt-a',
      timestamp: 'now',
      family: 'px4',
      board: 'rdk-rzv2h',
      core: 'cr8_0',
      selectionId: 'a',
      target: 'another-target',
      gitRevision: 'fixture',
      gitDirty: false,
      compiler: 'fixture',
      artifacts: [{ path: 'fixture.elf', sha256: 'a'.repeat(64), size: 1, core: 'cr8_0' }],
      status: 'committed',
    }));
    assert.strictEqual(restoredStore.getReceiptPath(selection), null, 'receipt target changes must invalidate the persisted binding');
    await restoredStore.setSelection({ ...selection, id: 'different' });
    assert.strictEqual(restoredStore.getReceiptPath(), null, 'selection changes must invalidate the active receipt binding');
    console.log('  ✓ receipt bindings persist per folder and invalidate on profile identity changes');
    await restoredStore.setSelection(selection);
    const externalReceiptDir = path.join(fakeBackendRoot, 'build', 'workspace-artifacts', 'external-run');
    fs.mkdirSync(externalReceiptDir, { recursive: true });
    const externalReceiptPath = path.join(externalReceiptDir, 'receipt.json');
    const externalReceipt = { ...JSON.parse(fs.readFileSync(receiptPath, 'utf8')), receiptId: 'external-run', target: 'x', timestamp: '2026-10-25T12:00:00Z' };
    fs.writeFileSync(externalReceiptPath, JSON.stringify(externalReceipt));
    restoredStore.refreshReceipts();
    assert.strictEqual(restoredStore.getReceiptPath(), path.relative(fakeBackendRoot, externalReceiptPath));
    const { ArtifactsViewProvider } = sourceModule('views/artifacts-view');
    const artifactView = new ArtifactsViewProvider(fakeBackendRoot, restoredStore);
    assert.strictEqual(artifactView.getReceipt().receiptId, 'external-run');
    fs.unlinkSync(externalReceiptPath);
    restoredStore.refreshReceipts();
    artifactView.refresh();
    assert.strictEqual(restoredStore.getReceiptPath(), null);
    assert.strictEqual(artifactView.getReceipt(), null);
    console.log('  ✓ external CLI receipts refresh by exact selection and removal clears view/commands');
    const unrelatedRoot = path.join(temporary, 'unrelated');
    const secondRoot = path.join(temporary, 'second firmware');
    fs.mkdirSync(unrelatedRoot);
    fs.mkdirSync(path.join(secondRoot, 'Tools'), { recursive: true });
    fs.writeFileSync(path.join(secondRoot, 'Tools', 'firmware-workspace.py'), 'raise RuntimeError("must not execute in Restricted Mode")');
    const originalFolders = workspace.workspaceFolders;
    workspace.workspaceFolders = [
      { name: 'unrelated', uri: vscode.Uri.file(unrelatedRoot) },
      { name: 'first firmware', uri: vscode.Uri.file(fakeBackendRoot) },
      { name: 'second firmware', uri: vscode.Uri.file(secondRoot) },
    ];
    workspace.isTrusted = false;
    let shownStatus = false, capturedTaskProvider;
    vscode.StatusBarAlignment = { Left: 1 };
    vscode.MarkdownString = class { constructor(value) { this.value = value; } };
    vscode.window.createStatusBarItem = () => ({ show: () => { shownStatus = true; }, dispose: () => {} });
    vscode.window.registerTreeDataProvider = () => ({ dispose: () => {} });
    vscode.debug.registerDebugConfigurationProvider = () => ({ dispose: () => {} });
    vscode.tasks = { registerTaskProvider: (_type, provider) => { capturedTaskProvider = provider; return { dispose: () => {} }; } };
    vscode.window.showQuickPick = async (items) => {
      assert.strictEqual(items.length, 2, 'unrelated folder must be excluded from workspace routing');
      return items.find((item) => item.folder.uri.fsPath === secondRoot);
    };
    const entry = sourceModule('extension');
    const activationContext = { ...extensionContext, subscriptions: [] };
    entry.activate(activationContext);
    await new Promise((resolve) => setImmediate(resolve));
    assert.ok(capturedTaskProvider, 'activation must initialize the explicitly selected folder');
    assert.ok(shownStatus, 'native status identity must be visible');
    assert.ok(!fs.existsSync(path.join(secondRoot, '.vscode')), 'untrusted activation must not write selection files');
    assert.deepStrictEqual(capturedTaskProvider.provideTasks(), [], 'untrusted tasks must remain unavailable');
    workspace.isTrusted = true;
    const routedTasks = capturedTaskProvider.provideTasks();
    assert.ok(routedTasks.every((task) => task.execution.options.cwd === secondRoot));
    assert.ok(routedTasks.every((task) => task.scope.uri.fsPath === secondRoot));
    const secondStore = new SelectionStore(extensionContext, secondRoot);
    assert.strictEqual(secondStore.getReceiptPath(), null, 'another folder must not inherit the first folder receipt');
    await entry.deactivate();
    workspace.workspaceFolders = originalFolders;
    console.log('  ✓ real activation routes past unrelated folder to chosen firmware root, with no untrusted writes');

  } finally {
    Module._load = originalLoad;
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

runBehavioralTests().then(() => {
  console.log('== All Extension Tests Passed ==\n');
}).catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
