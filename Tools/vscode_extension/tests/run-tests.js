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
assert.ok(pkg.contributes.views['px4-nuttx-workspace'].length >= 5, 'Must define all five native views');
assert.ok(pkg.contributes.views['px4-nuttx-workspace'].some((view) => view.id === 'px4-nuttx.dualCoreLoader'));
for (const action of ['browse', 'folder', 'useBuild', 'buildBoth', 'validate', 'loadBoth', 'recoverBoth', 'debugR80', 'debugR81', 'keepCaptured', 'importUpdated', 'resume']) {
  assert.ok(pkg.contributes.commands.some((command) => command.command === `px4Nuttx.dual.${action}`), `Missing dual-core action ${action}`);
}
assert.equal(pkg.contributes.views['px4-nuttx-workspace'].find((view) => view.id === 'px4-nuttx.dualCoreLoader').name, 'Firmware Setup');
for (const action of ['select', 'saveAs', 'rename', 'buildCore', 'buildBoth', 'buildAndLoad', 'stopSessions']) {
  const command = pkg.contributes.commands.find((entry) => entry.command === `px4Nuttx.setup.${action}`);
  assert.ok(command?.enablement.includes('px4Nuttx.savedSetupOperationsReady'), `Missing runtime rollout context for ${action}`);
}
assert.ok(pkg.contributes.views['px4-nuttx-workspace'].filter((view) => ['px4-nuttx.selection', 'px4-nuttx.operations'].includes(view.id)).every((view) => view.when === '!px4Nuttx.savedSetupActive'));
assert.ok(pkg.contributes.commands.length >= 8, 'Must contribute commands');
assert.ok(pkg.contributes.jsonValidation.length >= 3, 'Must contribute schema validations');
console.log('  ✓ package.json contributes all required views, commands, and schemas');

// Firmware chords must preserve normal editing and stay within an initialized workspace.
const shortcutContext = {
  'px4Nuttx.workspaceReady': true,
  isWorkspaceTrusted: true,
  inputFocus: false,
  terminalFocus: false,
  'px4Nuttx.savedSetupActive': false,
};
for (const binding of pkg.contributes.keybindings) {
  const reservedPrefixes = ['alt+r', 'alt+cmd+r', 'alt+ctrl+r'].map((key) => key.split('+').sort().join('+'));
  for (const key of [binding.key, binding.mac].filter(Boolean)) {
    const prefix = key.split(' ')[0].split('+').sort().join('+');
    assert.ok(!reservedPrefixes.includes(prefix), 'firmware chords must preserve regex and existing reveal/session shortcuts');
  }
  // These contributions use conjunctions of boolean context keys.
  const enabled = (context) => !!binding.when && binding.when.split(/\s*&&\s*/).every((term) =>
    term.startsWith('!') ? !context[term.slice(1)] : !!context[term]);
  assert.equal(enabled(shortcutContext), true, `${binding.command} must be available in its workspace`);
  for (const context of [
    { ...shortcutContext, 'px4Nuttx.workspaceReady': false },
    { ...shortcutContext, isWorkspaceTrusted: false },
    { ...shortcutContext, inputFocus: true },
    { ...shortcutContext, terminalFocus: true },
  ]) {
    assert.equal(enabled(context), false, `${binding.command} must respect workspace, trust and focus`);
  }
  const singleCoreOnly = ['px4Nuttx.load', 'px4Nuttx.attach'].includes(binding.command);
  assert.equal(enabled({ ...shortcutContext, 'px4Nuttx.savedSetupActive': true }), !singleCoreOnly);
}
console.log('  ✓ firmware shortcuts preserve regex search, text inputs, terminals and workspace guards');

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
const vsixCandidate1 = path.join(EXT_DIR, 'px4-nuttx-dashboard-0.1.0.vsix');
const vsixCandidate2 = path.join(EXT_DIR, 'px4-nuttx-firmware-workspace-0.1.0.vsix');
const vsixFile = fs.existsSync(vsixCandidate1) ? vsixCandidate1 : vsixCandidate2;
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
  class MarkdownString { constructor(value) { this.value = value; } }
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
  const contexts = new Map();
  let lastDebugSession;
  const vscode = {
    EventEmitter,
    CancellationTokenSource: class { constructor() { this.event = new EventEmitter(); this.token = { isCancellationRequested: false, onCancellationRequested: this.event.event }; } cancel() { this.token.isCancellationRequested = true; this.event.fire(); } dispose() {} },
    TreeItem,
    ThemeIcon,
    MarkdownString,
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
      onDidCloseTerminal: () => ({ dispose() {} }),
      createTerminal: () => ({ show() {}, dispose() {} }),
      showInformationMessage: async () => undefined,
      showErrorMessage: async () => undefined,
      showWarningMessage: async () => undefined,
      showInputBox: async () => undefined,
      showQuickPick: async () => undefined,
      withProgress: async (_, callback) => callback({ report: () => {} }, { isCancellationRequested: false }),
    },
    commands: {
      registerCommand: (id, callback) => { registered.set(id, callback); return { dispose: () => registered.delete(id) }; },
      executeCommand: async (id, ...args) => id === 'setContext' ? contexts.set(args[0], args[1]) : registered.get(id)?.(...args),
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
    let probeAcquisitions = 0;
    let loadedLease, attachedLease;
    let loadOutcome = { status: 'blocked', data: { recoveryRequired: true }, diagnostics: [{ message: 'blocked' }] };
    const executionStore = {
      setSessionGuard() {}, notifySessionChange() {}, assertMutable() {}, getActiveSetup() {}, getPreparedPair() {}, captureSetupToken() { return {}; }, isSetupTokenCurrent() { return true; },
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
      getWorkspaceRoot: () => REPO_ROOT,
      probeLeases: {
        acquire: async (serial) => { probeAcquisitions++; return { lease: { leaseToken: 'execution-lease', serial }, release: async () => {} }; },
      },
      loadTarget: async (...args) => { loadCalls += 1; loadedLease = args[3].lease; return loadOutcome; },
      buildSelection: async () => ({ status: 'ok', data: {}, diagnostics: [], receiptPath: 'receipt-a.json' }),
    };
    const executionController = registerExecutionCommands(selectionContext, executionClient, executionStore, {
      hasOwnedSessions: () => false,
      startManagedAttach: async (...args) => { attached += 1; attachedLease = args[4]; return true; },
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
    for (const removed of ['px4Nuttx.startConsole', 'px4Nuttx.stopConsole', 'px4Nuttx.setup.consoleCore', 'px4Nuttx.setup.device']) {
      assert.ok(!registered.has(removed), `${removed} must not be registered: consoles are manual`);
      assert.ok(!pkg.contributes.commands.some((command) => command.command === removed), `${removed} must not be contributed`);
    }
    assert.ok(!('px4Nuttx.consolePort' in pkg.contributes.configuration.properties), 'console port setting is retired');
    assert.ok(!('stopConsoleForHandoff' in executionController), 'load/debug ownership is the probe lease alone');
    console.log('  ✓ no extension-managed console: commands, settings and handoff are gone');
    const normalReceiptLookup = executionStore.getReceiptPath;
    const normalReceiptBinding = executionStore.setReceiptPath;
    const normalBuild = executionClient.buildSelection;
    const normalWarning = vscode.window.showWarningMessage;
    const hardwareCalls = () => [probeAcquisitions, loadCalls, attached];
    let offeredReceipt;
    let offeredBuilds = 0;
    executionStore.getReceiptPath = () => offeredReceipt;
    executionStore.setReceiptPath = async (value) => { offeredReceipt = value; };
    vscode.window.showWarningMessage = async () => 'Build Target';
    executionClient.buildSelection = async () => {
      offeredBuilds++;
      return { status: 'ok', data: {}, diagnostics: [], receiptPath: 'receipt-a.json' };
    };
    for (const mode of ['incremental', 'clean']) {
      currentSelection = { ...selection, build: { ...selection.build, mode } };
      for (const command of ['px4Nuttx.load', 'px4Nuttx.recoverLoad', 'px4Nuttx.attach', 'px4Nuttx.loadAndDebug']) {
        offeredReceipt = null;
        const before = hardwareCalls();
        const buildsBefore = offeredBuilds;
        assert.equal(await registered.get(command)(), false, `${command} must stop after its offered build`);
        assert.equal(offeredBuilds, buildsBefore + 1);
        assert.equal(offeredReceipt, 'receipt-a.json', 'successful build must remain available for the next explicit action');
        assert.deepEqual(hardwareCalls(), before, `${command} must not reserve J-Link, load, or attach after building`);
      }
    }
    currentSelection = selection;
    for (const outcome of ['ok', 'failed', 'cancelled']) {
      const cleanOptions = [];
      executionClient.buildSelection = async (_selectionPath, options) => {
        cleanOptions.push(options.clean);
        return { status: outcome, data: {}, diagnostics: [], receiptPath: outcome === 'ok' ? 'receipt-a.json' : null };
      };
      const before = hardwareCalls();
      for (const command of ['px4Nuttx.build', 'px4Nuttx.cleanRebuild']) { await registered.get(command)(); }
      assert.deepEqual(cleanOptions, [false, true]);
      assert.deepEqual(hardwareCalls(), before, `${outcome} Build and Clean Rebuild must never start a target operation`);
    }
    executionStore.getReceiptPath = normalReceiptLookup;
    executionStore.setReceiptPath = normalReceiptBinding;
    executionClient.buildSelection = normalBuild;
    vscode.window.showWarningMessage = normalWarning;
    console.log('  ✓ build and clean stay host-only, including builds offered by load/debug prompts');
    executionStore.getReceiptPath = () => null;
    vscode.window.showWarningMessage = async () => 'Build Target';
    executionClient.buildSelection = async () => {
      currentSelection = { ...selection, id: 'changed-during-build' };
      return { status: 'ok', data: {}, diagnostics: [], receiptPath: 'receipt-a.json' };
    };
    const callsBeforeBuildSwitch = loadCalls;
    assert.strictEqual(await registered.get('px4Nuttx.loadAndDebug')(), false);
    assert.strictEqual(loadCalls, callsBeforeBuildSwitch, 'selection change during build must not retarget a composite operation');
    executionStore.getReceiptPath = normalReceiptLookup;
    vscode.window.showWarningMessage = normalWarning;
    currentSelection = selection;


    let failedHandleReleases = 0;
    const failingManager = new ProbeLeaseManager({ startProbeSession: async (serial) => ({ lease: { serial, leaseToken: 'uncertain' },
      isReleased: () => false, release: async () => { failedHandleReleases++; throw new Error('supervisor teardown uncertain'); }, sendEvent() {} }) });
    const failingHandle = await failingManager.acquire('probe');
    await assert.rejects(failingHandle.release(), /uncertain/);
    await assert.rejects(failingHandle.release(), /uncertain/, 'repeated teardown must not report success after a failure');
    assert.equal(failedHandleReleases, 1, 'all teardown callers join one acknowledgement');
    await assert.rejects(failingManager.acquire('probe'), /already reserved/);
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
    const manualConfiguration = { type: 'cortex-debug', request: 'attach', name: 'Developer JSONC', executable: '/my symbols.elf', custom: { keep: true } };
    const developerLaunch = path.join(temporary, 'launch.json');
    const developerJsonc = '// developer comment\n{ "version": "0.2.0", "configurations": [], }\n'; fs.writeFileSync(developerLaunch, developerJsonc);
    const beforeManualRelease = leaseReleases;
    assert.equal(debugProvider.resolveDebugConfiguration(undefined, manualConfiguration), manualConfiguration, 'unmanaged config passes through by identity');
    assert.equal(leaseReleases, beforeManualRelease); assert.equal(fs.readFileSync(developerLaunch, 'utf8'), developerJsonc);
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
    assert.equal(fs.readFileSync(developerLaunch, 'utf8'), developerJsonc, 'managed operations preserve developer JSONC bytes');
    let failedRelease = true;
    const failingDebug = new Px4NuttxDebugProvider({
      probeLeases: { acquire: async () => ({ lease: { serial: 'probe', leaseToken: 'failed-start' }, release: async () => { if (failedRelease) { throw new Error('release pending'); } } }) },
      getDebugConfig: async () => ({ status: 'failed', data: {}, diagnostics: [] }),
    }, executionStore);
    assert.equal(await failingDebug.startManagedAttach('receipt-a.json', 'cr8_0', selection, 'probe'), false);
    assert.equal(failingDebug.hasOwnedSessions(), true, 'failed startup release retains ownership');
    await assert.rejects(failingDebug.disposeAsync(), /release pending/);
    failedRelease = false; await failingDebug.disposeAsync(); assert.equal(failingDebug.hasOwnedSessions(), false);
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
    const cancelFixture = () => cancellationListeners.forEach((listener) => listener());
    const cancellationDeadline = setTimeout(cancelFixture, 5000);
    const cancellationResultPromise = fixtureClient.executeCommand('slow', [], {
      cancellationToken: { onCancellationRequested: (listener) => { cancellationListeners.push(listener); return { dispose: () => {} }; } },
      onOutput: (chunk, stream) => {
        streamed.push({ chunk, stream });
        if (stream === 'stderr' && chunk.includes('live-fixture')) { queueMicrotask(cancelFixture); }
      },
    });
    const cancellationResult = await cancellationResultPromise;
    clearTimeout(cancellationDeadline);
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
    await persistentStore.setReceiptPath('receipt.json', selection);
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
    await restoredStore.refreshReceipts();
    assert.strictEqual(restoredStore.getReceiptPath(), path.relative(fakeBackendRoot, externalReceiptPath));
    const { ArtifactsViewProvider } = sourceModule('views/artifacts-view');
    const artifactView = new ArtifactsViewProvider(fakeBackendRoot, restoredStore);
    assert.strictEqual(artifactView.getReceipt().receiptId, 'external-run');
    const artifactRows = await artifactView.getChildren();
    assert.equal(artifactRows.find((item) => item.label === 'fixture.elf').description, path.join(fakeBackendRoot, 'fixture.elf'),
      'Artifacts must show the captured ELF filename and full path inline');
    fs.unlinkSync(externalReceiptPath);
    await restoredStore.refreshReceipts();
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
    assert.equal(contexts.get('px4Nuttx.workspaceReady'), true);
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
    assert.equal(contexts.get('px4Nuttx.workspaceReady'), false, 'shutdown must disable firmware shortcuts');
    // Shutdown wins while the multi-root picker is unresolved. It must not hang
    // or register resources if the old picker resolves later.
    let resolveLateFolder;
    vscode.window.showQuickPick = () => new Promise((resolve) => { resolveLateFolder = resolve; });
    const beforeLateTask = capturedTaskProvider;
    entry.activate({ ...activationContext, subscriptions: [] });
    assert.equal(contexts.get('px4Nuttx.workspaceReady'), false, 'an unresolved workspace must not enable shortcuts');
    await entry.deactivate();
    resolveLateFolder({ folder: workspace.workspaceFolders[2] });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(capturedTaskProvider, beforeLateTask);
    assert.equal(contexts.get('px4Nuttx.workspaceReady'), false, 'a late picker must not re-enable shortcuts');
    workspace.workspaceFolders = [workspace.workspaceFolders[0]];
    entry.activate({ ...activationContext, subscriptions: [] });
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(contexts.get('px4Nuttx.workspaceReady'), false, 'unrelated workspaces must not enable shortcuts');
    await entry.deactivate();
    workspace.workspaceFolders = originalFolders;
    console.log('  ✓ real activation routes past unrelated folder to chosen firmware root, with no untrusted writes');

  } finally {
    Module._load = originalLoad;
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

runBehavioralTests().then(() => require('./dual-core-loader-tests')()).then(() => {
  console.log('== All Extension Tests Passed ==\n');
}).catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
