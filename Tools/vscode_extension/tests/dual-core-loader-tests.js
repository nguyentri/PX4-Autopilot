const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const Module = require('module');
const crypto = require('crypto');
const esbuild = require('../node_modules/esbuild');

async function runDualCoreTests() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dual core ui '));
  const registered = new Map();
  const saved = new Map();
  const errors = [];
  let rejectPersistence = false;
  let picker;
  class EventEmitter {
    constructor() { this.listeners = []; this.event = (fn) => { this.listeners.push(fn); return { dispose: () => {} }; }; }
    fire(value) { for (const fn of this.listeners) { fn(value); } }
    dispose() {}
  }
  const vscode = {
    EventEmitter, TreeItem: class { constructor(label) { this.label = label; } },
    ThemeIcon: class { constructor(id, color) { this.id = id; this.color = color; } },
    TreeItemCollapsibleState: { None: 0 }, ProgressLocation: { Notification: 1 }, Uri: { file: (file) => ({ fsPath: file, scheme: 'file' }) },
    workspace: { isTrusted: true, getConfiguration: () => ({ get: (_, fallback) => fallback }) },
    window: { onDidCloseTerminal: () => ({ dispose() {} }), showErrorMessage: async (text) => errors.push(text), showWarningMessage: async () => 'Use Declared Image',
      showInformationMessage: async () => {}, showOpenDialog: async () => undefined,
      showQuickPick: async (items) => picker?.(items), withProgress: async (_, fn) => fn({ report() {} }, { isCancellationRequested: false }) },
    commands: { executeCommand: async () => {}, registerCommand: (name, fn) => { registered.set(name, fn); return { dispose() {} }; } },
  };
  const context = { subscriptions: [], workspaceState: { get: (key) => saved.get(key), update: async (key, value) => {
    if (rejectPersistence) { throw new Error('disk full'); } saved.set(key, JSON.parse(JSON.stringify(value)));
  } } };
  const originalLoad = Module._load;
  Module._load = function(name, parent, main) { return name === 'vscode' ? vscode : originalLoad.call(this, name, parent, main); };
  function source(name) {
    const file = path.resolve(__dirname, '../src', `${name}.ts`);
    const output = esbuild.buildSync({ entryPoints: [file], bundle: true, platform: 'node', format: 'cjs', write: false, external: ['vscode'], logLevel: 'silent' }).outputFiles[0].text;
    const compiled = new Module(file, module);
    compiled.filename = file; compiled.paths = Module._nodeModulePaths(path.dirname(file)); compiled._compile(output, file); return compiled.exports;
  }
  try {
    const { SelectionStore } = source('selection-store');
    const { DualCoreLoaderController, scanElfCandidates, observeSource, pairDigest } = source('dual-core-loader-controller');
    const { DualCoreLoaderViewProvider } = source('views/dual-core-loader-view');
    const { parseProgressLine } = source('backend-client');
    const { registerExecutionCommands } = source('commands-execution');
    const groups = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../profiles/groups.json'))).groups;
    for (const group of Object.values(groups)) { group.definitionSha256 = 'a'.repeat(64); }
    const catalog = { groups, capabilities: { importImages: 1, receiptVersions: [1, 2], preparedIdentity: 1, strictLoadedIdentity: 1, targetHistory: 1 }, devices: {}, px4Targets: [], nuttxConfigs: {} };
    const selection = { schemaVersion: 1, id: 'rzv-native-ipc-rtt', board: 'rdk-rzv2h', core: 'multicore', group: 'rzv-native-ipc-rtt', build: { family: 'nuttx', mode: 'incremental' } };
    const store = new SelectionStore(context, root); store.setCatalog(catalog); await store.setSelection(selection); await store.setSelectedCore('cr8_1'); await store.setSelectedProbe('fixture');
    const one = path.join(root, 'nuttx'); const two = path.join(root, 'other.elf');
    fs.writeFileSync(one, Buffer.from('\x7fELFfirst')); fs.writeFileSync(two, Buffer.from('\x7fELFsecond'));
    let imports = 0;
    const backend = { importImages: async (file) => {
      imports++;
      assert.equal(store.isPreparingImages(), true, 'import execution must publish live activity');
      const pair = (await preparationView.getChildren()).find((row) => row.label === 'Pair');
      assert.equal(pair.description, store.hasWorkflow() ? 'Firmware workflow in progress' : 'Preparing images');
      assert.equal(pair.iconPath.id, 'sync~spin');
      const request = JSON.parse(fs.readFileSync(file));
      const run = path.join(root, 'build', 'workspace-artifacts', `import-${request.requestId}`); fs.mkdirSync(run, { recursive: true });
      const artifacts = [];
      for (const [core, input] of Object.entries(request.sources)) {
        const prior = 'receiptPath' in input ? JSON.parse(fs.readFileSync(input.receiptPath)).artifacts.find((item) => item.core === core) : undefined;
        const src = prior?.path || (input.kind === 'folder' ? path.join(input.path, input.relativePath) : input.path);
        const dest = path.join(run, core + '.elf'); fs.copyFileSync(src, dest);
        artifacts.push({ core, path: dest, size: fs.statSync(dest).size, sha256: crypto.createHash('sha256').update(fs.readFileSync(dest)).digest('hex'),
          sourceObservation: prior?.sourceObservation || await observeSource(src), provenance: { evidence: 'developer-declared' } });
      }
      const receiptPath = path.join(run, 'receipt.json'); const receiptId = `import-${request.requestId}`;
      fs.writeFileSync(receiptPath, JSON.stringify({ schemaVersion: 2, receiptId, timestamp: 'now', family: request.selection.build.family, board: request.selection.board,
        core: 'multicore', selectionId: request.selection.id, group: request.selection.group, groupDefinitionSha256: 'a'.repeat(64), status: artifacts.length === 2 ? 'committed' : 'provisional', artifacts }));
      return { status: 'ok', receiptPath, data: { requestId: request.requestId, receiptId, preparationState: artifacts.length === 2 ? 'ready' : 'partial', artifacts, groupDefinitionSha256: 'a'.repeat(64) } };
    }, runDoctor: async () => ({ data: { targetHistory: { recoveryRequired: false } } }) };
    let target;
    const execution = { buildSelectedGroup: async () => { throw new Error('must not build implicitly'); },
      loadPrepared: async (request, options) => { target = { request, options }; return { status: 'ok' }; }, debugPrepared: async () => true };
    const controller = new DualCoreLoaderController(backend, store, execution);
    const preparationView = new DualCoreLoaderViewProvider(store);
    const member = (core) => groups[selection.group].members.find((item) => item.core === core);
    const file = (core, filePath) => ({ kind: 'file', path: filePath, declaration: member(core) });
    const preparationEvents = [];
    const preparationSubscription = store.onDidChangeSelection(() => preparationEvents.push(store.isPreparingImages()));
    await controller.assign('cr8_0', file('cr8_0', one));
    assert.ok(preparationEvents.includes(true), 'live preparation must refresh the view');
    assert.equal(preparationEvents.at(-1), false, 'completed preparation must refresh the view without a spinner');
    preparationSubscription.dispose();
    assert.equal(store.getPreparedPair().prepared.artifacts.length, 1);
    fs.writeFileSync(one, Buffer.from('\x7fELFreplaced'));
    await controller.assign('cr8_1', file('cr8_1', two));
    assert.equal(await controller.validate(), false);
    assert.ok(store.getPreparedPair().sourceChanges.cr8_0);
    await controller.keepCaptured('cr8_0'); assert.equal(await controller.validate(), true);
    assert.ok(store.getPreparedPair().acknowledged.cr8_0);
    const restored = new SelectionStore(context, root); restored.setCatalog(catalog);
    assert.deepEqual(restored.getPreparedPair(), store.getPreparedPair()); assert.equal(restored.getSelectedCore(), 'cr8_1');
    const pinned = store.getReceiptPath(); store.refreshReceipts(); assert.equal(store.getReceiptPath(), pinned);
    assert.equal(await controller.targetAction('load'), true); assert.equal(target.options.allowImplicitBuild, false);
    assert.equal(target.request.receiptPath, pinned); assert.equal(imports, 2);
    assert.equal(target.request.pairSha256, pairDigest(selection, 'a'.repeat(64), target.request.artifactDigests));
    fs.writeFileSync(one, Buffer.from('\x7fELFreplaced again'));
    assert.equal(await controller.validate(), false); assert.ok(store.getPreparedPair().sourceChanges.cr8_0, 'second source change must require another choice');
    await controller.importUpdated('cr8_0'); assert.equal(await controller.validate(), true);
    const sourceBeforeDelete = fs.readFileSync(one);
    const capturedBeforeDelete = store.getPreparedPair().prepared.receiptId;
    fs.unlinkSync(one);
    assert.equal(await controller.validate(), false);
    assert.equal(store.getPreparedPair().sourceChanges.cr8_0.sha256, 'missing');
    const afterSourceDeletion = new SelectionStore(context, root);
    assert.equal(afterSourceDeletion.getStateError(), undefined, 'a deleted original is valid saved state after reload');
    afterSourceDeletion.setCatalog(catalog); await afterSourceDeletion.initialize();
    assert.equal(afterSourceDeletion.getPreparedPair().prepared.receiptId, capturedBeforeDelete);
    const deletionController = new DualCoreLoaderController(backend, afterSourceDeletion, execution);
    await deletionController.keepCaptured('cr8_0'); assert.equal(await deletionController.validate(), true);
    deletionController.dispose(); afterSourceDeletion.dispose();
    fs.writeFileSync(one, sourceBeforeDelete);
    await controller.importUpdated('cr8_0'); assert.equal(await controller.validate(), true);
    // Validation begins first, but its state write reaches the queue after a new pending choice.
    const beforeRace = store.getPreparedPair();
    let releaseRead, releaseWrite, enteredRead = false, enteredWrite = false, validationQueued = false;
    const readGate = new Promise((resolve) => { releaseRead = resolve; });
    const writeGate = new Promise((resolve) => { releaseWrite = resolve; });
    const originalRead = fs.createReadStream;
    const originalUpdate = context.workspaceState.update;
    const originalPairWrite = store.setPreparedPair.bind(store);
    const originalPairUpdate = store.updatePreparedPair?.bind(store);
    let firstRead = true;
    fs.createReadStream = function(filePath, ...args) {
      if (firstRead && filePath === beforeRace.prepared.receiptPath) {
        firstRead = false; enteredRead = true;
        return (async function*() { await readGate; for await (const chunk of originalRead(filePath, ...args)) { yield chunk; } })();
      }
      return originalRead(filePath, ...args);
    };
    context.workspaceState.update = async (key, value) => {
      if ((Object.values(value.setups || {}).find((entry) => entry.selection.group === selection.group)?.pair?.pending || value.imageAssignments?.[selection.group]?.pending) && !enteredWrite) { enteredWrite = true; await writeGate; }
      return originalUpdate(key, value);
    };
    store.setPreparedPair = async (group, value) => {
      if (enteredWrite && !value.pending && value.generation === beforeRace.generation) { validationQueued = true; }
      return originalPairWrite(group, value);
    };
    if (originalPairUpdate) {
      store.updatePreparedPair = (...args) => {
        if (enteredWrite) { validationQueued = true; }
        return originalPairUpdate(...args);
      };
    }
    const until = async (condition) => {
      for (let count = 0; count < 2000 && !condition(); count++) { await new Promise((resolve) => setTimeout(resolve, 1)); }
      assert.ok(condition(), 'controlled asynchronous boundary was not reached');
    };
    let raceOperations = [];
    try {
      const validation = controller.validate(); raceOperations.push(validation); await until(() => enteredRead);
      const third = path.join(root, 'third.elf'); fs.writeFileSync(third, Buffer.from('\x7fELFthird'));
      const assigning = controller.assign('cr8_0', file('cr8_0', third)); raceOperations.push(assigning); await until(() => enteredWrite);
      assert.throws(() => store.beginTargetTransition('Loading'), /Saving image selection/,
        'a target transition cannot start while a pair mutation is being persisted');
      releaseRead(); await until(() => validationQueued); releaseWrite();
      const [valid] = await Promise.all(raceOperations);
      assert.equal(valid, false, 'older validation must be discarded after a new choice');
      assert.equal(store.getPreparedPair().generation, beforeRace.generation + 1);
      assert.equal(store.getPreparedPair().sources.cr8_0.path, third);
      assert.equal(store.getPreparedPair().pending, undefined);
      const restoredAfterRace = new SelectionStore(context, root);
      assert.deepEqual(restoredAfterRace.getPreparedPair(), store.getPreparedPair(), 'the new pair must also survive reload');
      restoredAfterRace.dispose();
    } finally {
      releaseRead(); releaseWrite(); await Promise.allSettled(raceOperations);
      fs.createReadStream = originalRead; context.workspaceState.update = originalUpdate;
      store.setPreparedPair = originalPairWrite;
      if (originalPairUpdate) { store.updatePreparedPair = originalPairUpdate; }
    }
    await Promise.all([
      store.setPreparedPair('isolated-one', { generation: 1, sources: {} }),
      store.setPreparedPair('isolated-two', { generation: 2, sources: {} }),
    ]);
    assert.equal(store.getPreparedPair('isolated-one').generation, 1, 'queued group writes must preserve sibling assignments');
    assert.equal(store.getPreparedPair('isolated-two').generation, 2);
    let releases = 0, loadCalls = 0, debugCall;
    const realBackend = {
      probeLeases: { acquire: async (serial) => ({ lease: { serial, leaseToken: 'reserved' }, release: async () => { releases++; } }) },
      loadTarget: async (_selectionPath, receiptPath, serial, options) => {
        loadCalls++; assert.equal(receiptPath, store.getPreparedPair().prepared.receiptPath); assert.equal(serial, 'fixture');
        assert.equal(options.expectReceiptId, store.getPreparedPair().prepared.receiptId); assert.ok(options.operationInstanceId);
        await assert.rejects(store.setSelectedProbe('wrong'), /wait/);
        const state = store.getPreparedPair();
        await assert.rejects(store.setPreparedPair(selection.group, { ...state, generation: 999 }), /wait/);
        return { status: 'ok', data: { receiptId: options.expectReceiptId, pairSha256: options.expectPairSha256,
          operationInstanceId: options.operationInstanceId, groupDefinitionSha256: state.prepared.groupDefinitionSha256,
          artifactDigests: Object.fromEntries(state.prepared.artifacts.map((item) => [item.core, item.sha256])) } };
      },
    };
    const debugProvider = { hasOwnedSessions: () => false, setConsoleHandoff() {}, startManagedAttach: async (...args) => { debugCall = args; return args[6](); } };
    const actualExecution = registerExecutionCommands(context, realBackend, store, debugProvider, { refresh() {} });
    const prepared = store.getPreparedPair();
    const exactRequest = { selection, selectionPath: store.writeSelectionSnapshot(), receiptPath: prepared.prepared.receiptPath,
      receiptId: prepared.prepared.receiptId, pairGeneration: prepared.generation, groupDefinitionSha256: prepared.prepared.groupDefinitionSha256,
      pairSha256: prepared.prepared.pairSha256, operationInstanceId: crypto.randomUUID(), serial: 'fixture',
      artifactDigests: Object.fromEntries(prepared.prepared.artifacts.map((item) => [item.core, item.sha256])) };
    assert.equal((await actualExecution.loadPrepared(exactRequest, { recover: false, allowImplicitBuild: false })).status, 'ok');
    assert.equal(loadCalls, 1); assert.equal(releases, 1);
    assert.equal(await actualExecution.debugPrepared(exactRequest, 'cr8_0', { requireLoaded: true }), true);
    assert.equal(debugCall[1], 'cr8_0'); assert.equal(debugCall[5].receiptId, exactRequest.receiptId);
    assert.equal(await actualExecution.loadPrepared({ ...exactRequest, pairGeneration: -1 }, { recover: false, allowImplicitBuild: false }), null);
    assert.equal(loadCalls, 1, 'stale generation must not start a loader');
    const updateBeforeBlockedSave = context.workspaceState.update;
    let releaseBlockedSave;
    const blockedSave = new Promise((resolve) => { releaseBlockedSave = resolve; });
    context.workspaceState.update = async (key, value) => { await blockedSave; return updateBeforeBlockedSave(key, value); };
    const saving = store.setPreparedPair('isolated-three', { generation: 3, sources: {} });
    let refusedLeaseReleases = 0;
    const retainedLease = { lease: { serial: 'fixture', leaseToken: 'handoff' }, release: async () => { refusedLeaseReleases++; } };
    try {
      await assert.rejects(actualExecution.loadPrepared(exactRequest,
        { recover: false, allowImplicitBuild: false, retainedLease }), /Saving image selection/);
      await assert.rejects(actualExecution.debugPrepared(exactRequest, 'cr8_0',
        { requireLoaded: true, retainedLease }), /Saving image selection/);
      assert.equal(refusedLeaseReleases, 2, 'refused transitions must release retained probe handoffs');
      assert.equal(loadCalls, 1);
    } finally { releaseBlockedSave(); await saving; context.workspaceState.update = updateBeforeBlockedSave; }
    await actualExecution.disposeAsync();
    const doctor = backend.runDoctor;
    const deferred = [];
    backend.runDoctor = () => new Promise((resolve) => deferred.push(resolve));
    const oldHistory = controller.refreshHistory(); const newHistory = controller.refreshHistory();
    deferred[1]({ data: { targetHistory: { recoveryRequired: false, verifiedPair: {
      pairSha256: exactRequest.pairSha256, groupDefinitionSha256: exactRequest.groupDefinitionSha256,
      artifactDigests: exactRequest.artifactDigests, timestamp: 'newer',
    } } } });
    await newHistory;
    deferred[0]({ data: { targetHistory: { recoveryRequired: true } } }); await oldHistory;
    assert.equal(store.getPreparedPair().history.verified, true, 'late history must not overwrite a newer result');
    backend.runDoctor = doctor;
    const generationBeforeCancel = store.getPreparedPair().generation;
    await controller.pickSource('cr8_0', true);
    assert.equal(store.getPreparedPair().generation, generationBeforeCancel, 'cancelled folder selection must preserve the pair');
    vscode.window.showOpenDialog = async () => [{ fsPath: root, scheme: 'file' }];
    picker = (items) => {
      assert.ok(items.some((item) => item.label === 'nuttx'));
      assert.ok(items.some((item) => item.label === 'other.elf'));
      return items.find((item) => item.label === 'nuttx');
    };
    await controller.pickSource('cr8_0', true);
    assert.equal(store.getPreparedPair().sources.cr8_0.relativePath, 'nuttx', 'multiple candidates require the explicit chosen file');
    const importNormally = backend.importImages;
    backend.importImages = async (file) => { const result = await importNormally(file); rejectPersistence = true; return result; };
    await assert.rejects(controller.assign('cr8_0', file('cr8_0', one)), /disk full/);
    rejectPersistence = false; backend.importImages = importNormally;
    const pendingAfterDelivery = store.getPreparedPair().pending.request.requestId;
    assert.equal(store.isPreparingImages(), false, 'failed persistence must clear live activity');
    const interruptedStore = new SelectionStore(context, root); interruptedStore.setCatalog(catalog);
    assert.equal(interruptedStore.getPreparedPair().pending.request.requestId, pendingAfterDelivery);
    const interruptedView = new DualCoreLoaderViewProvider(interruptedStore);
    const interruptedRows = await interruptedView.getChildren();
    assert.equal(interruptedRows.find((row) => row.label === 'Pair').description, 'Preparation pending');
    assert.equal(interruptedRows.find((row) => row.label === 'Pair').iconPath.id, 'debug-pause', 'restored preparation must wait without spinning');
    assert.ok(interruptedRows.some((row) => row.label === 'Resume Preparation'));
    interruptedView.dispose();
    await controller.resume();
    assert.equal(store.getPreparedPair().pending, undefined);
    assert.equal(store.getPreparedPair().prepared.receiptId, `import-${pendingAfterDelivery}`);
    interruptedStore.dispose();
    const before = store.getPreparedPair(); rejectPersistence = true;
    await assert.rejects(store.setPreparedPair(selection.group, { ...before, generation: 999 }), /disk full/);
    assert.deepEqual(store.getPreparedPair(), before); rejectPersistence = false;
    store.beginTargetTransition('Loading'); await assert.rejects(controller.assign('cr8_0', file('cr8_0', one)), /wait/);
    await assert.rejects(store.setSelectedProbe('other'), /wait/); store.endTargetTransition();
    const view = new DualCoreLoaderViewProvider(store);
    const rows = await view.getChildren(); assert.ok(rows.some((item) => item.label === 'R8-0')); assert.ok(rows.some((item) => item.label === 'R8-1'));
    assert.equal(rows.find((row) => row.label === 'Pair').iconPath.id, 'pass-filled');
    for (const transition of ['Loading captured pair', 'Recovering captured pair', 'Attaching R8-0']) {
      store.beginTargetTransition(transition);
      try {
        assert.equal((await view.getChildren()).find((row) => row.label === 'Pair').iconPath.id, 'sync~spin');
      } finally { store.endTargetTransition(); }
    }
    await store.withSetupMutationGuard(async () => {
      assert.equal((await view.getChildren()).find((row) => row.label === 'Pair').iconPath.id, 'sync~spin');
    });
    assert.equal((await view.getChildren()).find((row) => row.label === 'Pair').iconPath.id, 'pass-filled', 'workflow completion must stop animation');
    assert.equal(rows.find((item) => item.label === 'R8-0').core, 'cr8_0', 'native context-menu arguments must retain the row core');
    assert.equal(new Set(rows.map((item) => item.id)).size, rows.length, 'native row identities must be unique');
    vscode.workspace.isTrusted = false;
    await assert.rejects(controller.assign('cr8_0', file('cr8_0', one)), /Trust/); assert.equal((await view.getChildren()).length, 1);
    vscode.workspace.isTrusted = true;
    const candidates = await scanElfCandidates(root, { isCancellationRequested: false }); assert.ok(candidates.includes('nuttx')); assert.ok(candidates.includes('other.elf'));
    await assert.rejects(scanElfCandidates(root, { isCancellationRequested: false }, 1), /narrower/);
    await assert.rejects(scanElfCandidates(root, { isCancellationRequested: true }), /cancelled/);
    const event = { eventVersion: 1, operationInstanceId: 'one', phase: 'load', core: 'cr8_0', state: 'begin', logPath: '/tmp/one' };
    assert.deepEqual(parseProgressLine('PX4_WORKSPACE_EVENT ' + JSON.stringify(event), 'one'), event);
    assert.equal(parseProgressLine('PX4_WORKSPACE_EVENT ' + JSON.stringify(event), 'other'), undefined);
    assert.equal(parseProgressLine('PX4_WORKSPACE_EVENT broken', 'one'), undefined);
    fs.writeFileSync(store.getPreparedPair().prepared.artifacts[0].path, 'tampered');
    assert.equal(await controller.validate(), false); assert.match(store.getPreparedPair().validationError, /Captured image changed/);
    const oldCatalog = { ...catalog, capabilities: {} }; store.setCatalog(oldCatalog);
    await assert.rejects(controller.validate(), /Update the extension/);
    await store.flushPersistence();
    const originalSetup = store.getActiveSetup();
    const originalPair = store.getPreparedPair();
    const oldToken = store.captureSetupToken('cr8_0');
    await store.saveActiveSetupAs('IPC last working');
    const variantId = store.getActiveSetup().id;
    assert.notEqual(variantId, originalSetup.id);
    assert.deepEqual(store.getPreparedPair(), originalPair, 'Save As retains immutable captures');
    await store.setPreparedPair(selection.group, { ...originalPair, generation: originalPair.generation + 1 });
    await store.activateSetup(originalSetup.id);
    assert.deepEqual(store.getPreparedPair(), originalPair, 'same-group variants have independent generations');
    assert.equal(store.isSetupTokenCurrent(oldToken), false, 'activation ABA invalidates old callbacks');
    const legacyKey = `px4Nuttx.folderState.${root}`;
    saved.set(legacyKey, { selection, receipts: {}, imageAssignments: {} });
    const afterOldWriter = new SelectionStore(context, root);
    assert.equal(afterOldWriter.listSavedSetups().length, 2, 'old whole-value writes cannot erase v2 variants');
    afterOldWriter.setCatalog(catalog); await afterOldWriter.initialize();
    await afterOldWriter.activateSetup(variantId);
    assert.equal(afterOldWriter.getPreparedPair().generation, originalPair.generation + 1);
    await afterOldWriter.setPreparedPair(selection.group, { ...afterOldWriter.getPreparedPair(), pending: {
      request: { schemaVersion: 1, requestId: crypto.randomUUID(), selection, sources: {} }, sourceDigest: 'a'.repeat(64),
    } });
    await assert.rejects(afterOldWriter.saveActiveSetupAs('pending copy'), /Resume Preparation/);
    await afterOldWriter.setPreparedPair(selection.group, { ...afterOldWriter.getPreparedPair(), pending: undefined });
    afterOldWriter.setSessionGuard(() => true);
    await assert.rejects(afterOldWriter.activateSetup(originalSetup.id), /Stop Sessions/);
    await assert.rejects(afterOldWriter.setSelection(selection), /Stop Sessions/);
    await assert.rejects(afterOldWriter.setSelectedCore('cr8_0'), /Stop Sessions/);
    await assert.rejects(afterOldWriter.setSelectedProbe('other'), /Stop Sessions/);
    afterOldWriter.setSessionGuard(() => false);
    const updateBeforeMirror = context.workspaceState.update;
    context.workspaceState.update = async (key, value) => {
      if (key === legacyKey) { throw new Error('mirror disk full'); }
      return updateBeforeMirror(key, value);
    };
    await afterOldWriter.renameSetup('Canonical survives');
    assert.equal(afterOldWriter.getActiveSetup().name, 'Canonical survives');
    assert.match(afterOldWriter.getCompatibilityWarning(), /durable/);
    context.workspaceState.update = updateBeforeMirror;
    await afterOldWriter.initialize();
    assert.equal(afterOldWriter.getCompatibilityWarning(), '');
    const migrationRoot = `${root}-migration`;
    const migrationKey = `px4Nuttx.folderState.${migrationRoot}`;
    const legacySelection = { ...selection, id: 'developer-custom-group-id' };
    saved.set(migrationKey, { selection: legacySelection, selectedProbeSerial: 'fixture', selectedCore: 'cr8_1', receipts: {},
      imageAssignments: { [selection.group]: originalPair, 'unknown-old-group': originalPair } });
    const migrated = new SelectionStore(context, migrationRoot); migrated.setCatalog(catalog); await migrated.initialize(); await migrated.flushPersistence();
    assert.deepEqual(migrated.getPreparedPair(), originalPair);
    assert.equal(migrated.getSelection().id, legacySelection.id, 'migration preserves custom legacy selection identity');
    assert.equal(migrated.listSavedSetups().length, 1, 'unknown legacy group must not become an executable setup');
    assert.deepEqual(saved.get(`${migrationKey}.setups.v2`).imageAssignments['unknown-old-group'], originalPair);
    const migratedBytes = JSON.stringify(saved.get(`${migrationKey}.setups.v2`));
    await migrated.initialize(); assert.equal(JSON.stringify(saved.get(`${migrationKey}.setups.v2`)), migratedBytes, 'migration is idempotent');
    migrated.dispose();
    const nullRoot = `${root}-null`; const nullKey = `px4Nuttx.folderState.${nullRoot}.setups.v2`; saved.set(nullKey, null);
    const nullStore = new SelectionStore(context, nullRoot); assert.match(nullStore.getStateError(), /malformed/);
    await assert.rejects(nullStore.setSelection(selection), /malformed/); assert.equal(saved.get(nullKey), null); nullStore.dispose();
    const futureRoot = `${root}-future`;
    const futureKey = `px4Nuttx.folderState.${futureRoot}.setups.v2`;
    const futureRecord = { schemaVersion: 99, valuable: 'preserve' }; saved.set(futureKey, futureRecord);
    const futureStore = new SelectionStore(context, futureRoot);
    await assert.rejects(futureStore.setSelection(selection), /unsupported or malformed/);
    assert.deepEqual(saved.get(futureKey), futureRecord);
    await afterOldWriter.withSetupMutationGuard(async (owner) => {
      await assert.rejects(afterOldWriter.setSelectedProbe('other'), /workflow/);
      await assert.rejects(afterOldWriter.withSetupMutationGuard(async () => {}), /workflow/);
      assert.equal(await afterOldWriter.updatePreparedPair(selection.group, (current) => ({ ...current }), afterOldWriter.captureSetupToken(), owner), true);
    });
    await afterOldWriter.setSelectedProbe('fixture');
    // Exact build receipt adoption preserves the immutable peer and never retargets the global selection.
    store.setCatalog(catalog); await store.initialize();
    let beforeBuildSelection = store.getSelection();
    const buildCalls = []; let buildFailure = false; let tamperBuild = false; let cancelBuild = false;
    execution.buildExact = async (building, clean, cancellation) => {
      buildCalls.push({ building, clean }); assert.equal(cancellation.isCancellationRequested, false);
      assert.deepEqual(store.getSelection(), beforeBuildSelection);
      await assert.rejects(store.activateSetup(variantId), /workflow/);
      if (buildFailure) { return { status: 'failed' }; }
      const cores = building.group ? ['cr8_0', 'cr8_1'] : [building.core];
      const folder = path.join(root, 'build', `exact-${buildCalls.length}`); fs.mkdirSync(folder, { recursive: true });
      const artifacts = cores.map((key) => {
        const artifactPath = path.join(folder, `${key}.elf`); fs.writeFileSync(artifactPath, Buffer.from(`\x7fELFbuilt-${buildCalls.length}-${key}`));
        return { core: key, path: artifactPath, size: fs.statSync(artifactPath).size, sha256: crypto.createHash('sha256').update(fs.readFileSync(artifactPath)).digest('hex') };
      });
      const exactReceipt = path.join(folder, 'receipt.json'); fs.writeFileSync(exactReceipt, JSON.stringify({ schemaVersion: 1,
        receiptId: `exact-${buildCalls.length}`, selectionId: building.id, board: building.board, core: building.core,
        status: 'committed', family: building.build.family, target: building.build.target, config: building.build.config,
        group: building.group, groupDefinitionSha256: building.group ? 'a'.repeat(64) : undefined, artifacts }));
      if (tamperBuild) { fs.appendFileSync(artifacts[0].path, 'changed'); }
      if (cancelBuild) { cancellation.isCancellationRequested = true; }
      return { status: 'ok', receiptPath: exactReceipt };
    };
    // Rebuild both first to replace the deliberately tampered capture used above.
    await controller.buildBoth(true);
    assert.equal(buildCalls[0].clean, true);
    const peer = store.getPreparedPair().prepared.artifacts.find((a) => a.core === 'cr8_1');
    const peerBytes = fs.readFileSync(peer.path);
    await controller.buildCore('cr8_0');
    assert.equal(buildCalls[1].building.group, undefined); assert.equal(buildCalls[1].building.core, 'cr8_0');
    assert.equal(buildCalls[1].building.build.config, member('cr8_0').config);
    assert.deepEqual(fs.readFileSync(store.getPreparedPair().prepared.artifacts.find((a) => a.core === 'cr8_1').path), peerBytes);
    const oldPairId = store.getPreparedPair().prepared.receiptId;
    await controller.buildAndLoad(); assert.equal(target.options.allowImplicitBuild, false);
    assert.notEqual(target.request.receiptId, oldPairId);
    assert.equal(target.request.receiptId, store.getPreparedPair().prepared.receiptId);
    assert.ok(target.request.workflowOwner); assert.ok(target.request.setupToken.setupId);
    const compositeLease = { lease: { serial: 'fixture', leaseToken: 'same-owner' }, release: async () => {} };
    execution.stopConsoleForHandoff = async () => ({ ok: true, lease: compositeLease });
    execution.debugPrepared = async (request, key, options) => {
      assert.equal(request, target.request, 'composite debug consumes the identical prepared request');
      assert.equal(options.retainedLease, compositeLease); assert.equal(key, store.getSelectedCore());
      await assert.rejects(store.setSelectedCore('cr8_0'), /workflow/);
      return true;
    };
    assert.equal(await controller.loadAndDebug(), true);
    assert.equal(target.options.retainedLease, compositeLease, 'one probe reservation spans grouped load and debug');
    const lastGood = store.getPreparedPair(); buildFailure = true;
    await controller.buildAndLoad(); assert.deepEqual(store.getPreparedPair().prepared, lastGood.prepared); buildFailure = false;
    cancelBuild = true; await controller.buildAndLoad(); assert.deepEqual(store.getPreparedPair().prepared, lastGood.prepared); cancelBuild = false;
    tamperBuild = true; await assert.rejects(controller.buildBoth(), /changed before capture/);
    assert.equal(store.hasWorkflow(), false); assert.deepEqual(store.getPreparedPair().prepared, lastGood.prepared);
    tamperBuild = false;
    const px4Selection = { ...selection, id: 'rzv-px4-dualcr8', group: 'rzv-px4-dualcr8', build: { family: 'px4', mode: 'incremental' } };
    await store.setSelection(px4Selection); beforeBuildSelection = store.getSelection();
    await controller.buildCore('cr8_1');
    assert.equal(buildCalls.at(-1).building.build.target, 'renesas_rdk-rzv2h-io-cr8_1_pwm');
    assert.equal(buildCalls.at(-1).building.build.family, 'px4');
    assert.equal(store.getPreparedPair().prepared.artifacts.length, 1, 'first per-core build remains partial');
    assert.equal(await controller.validate(), false);
    await store.setSelection(selection);
    store.setSetupOperationsReady(false);
    const beforeDisabled = imports;
    assert.equal(await registered.get('px4Nuttx.dual.loadBoth')(), false);
    assert.equal(imports, beforeDisabled);
    assert.ok((await view.getChildren()).every((row) => !row.command), 'preview rows must be read-only before readiness');
    store.setSetupOperationsReady(true);
    const staleRow = (await view.getChildren()).find((row) => row.label === 'R8-0');
    assert.equal(staleRow.command.arguments[0].setupId, store.getActiveSetup().id);
    await store.activateSetup(variantId); await store.activateSetup(originalSetup.id);
    assert.equal(await registered.get('px4Nuttx.dual.browse')(staleRow), false, 'stale context-menu item is invalid after ABA');
    console.log('  ✓ exact per-core/all builds, immutable peer, explicit Build & Load, failed/tampered receipt and logical guard contracts');
    afterOldWriter.dispose(); futureStore.dispose();
    console.log('  ✓ saved setup isolation, ABA, old-writer rollback, pending clone, mirror recovery, session guards and future state');
    controller.dispose(); view.dispose(); store.dispose(); restored.dispose();
    console.log('  ✓ dual-core capture, restoration, source choices, pinned load, persistence, trust, scan and progress contracts');
  } finally { Module._load = originalLoad; fs.rmSync(root, { recursive: true, force: true }); }
}

module.exports = runDualCoreTests;
if (require.main === module) { runDualCoreTests().catch((error) => { console.error(error); process.exitCode = 1; }); }
