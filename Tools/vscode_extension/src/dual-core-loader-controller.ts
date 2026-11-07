import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { BackendClient } from './backend-client';
import { ExecutionController } from './commands-execution';
import { SelectionStore } from './selection-store';
import { FirmwareImport, FirmwareSelection, ImageSource, PreparedExecutionRequest, PreparedPairState, R8Core, SourceObservation, SetupOperationToken } from './types';

const CORES: R8Core[] = ['cr8_0', 'cr8_1'];
const hash = (value: string | Buffer): string => crypto.createHash('sha256').update(value).digest('hex');

export async function fileDigest(file: string): Promise<string> {
  const digest = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(file)) { digest.update(chunk); }
  return digest.digest('hex');
}

export async function observeSource(file: string): Promise<SourceObservation> {
  try {
    const before = await fs.promises.stat(file, { bigint: true });
    const sha256 = await fileDigest(file);
    const after = await fs.promises.stat(file, { bigint: true });
    if (before.ino !== after.ino || before.size !== after.size || before.mtimeNs !== after.mtimeNs || before.ctimeNs !== after.ctimeNs) {
      throw new Error('Source changed while checking it.');
    }
    return { path: file, sha256, size: Number(after.size), mtimeNs: String(after.mtimeNs) };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') { return { path: file, sha256: 'missing', size: 0, mtimeNs: '0' }; }
    throw error;
  }
}

/** Bounded traversal never follows folder symlinks or silently truncates results. */
export async function scanElfCandidates(root: string, token: vscode.CancellationToken, limit = 10000): Promise<string[]> {
  const pending = [''];
  const candidates: string[] = [];
  let visited = 0;
  while (pending.length) {
    if (token.isCancellationRequested) { throw new Error('Folder scan cancelled; no selection changed.'); }
    const relative = pending.pop()!;
    for (const entry of await fs.promises.readdir(path.join(root, relative), { withFileTypes: true })) {
      if (token.isCancellationRequested) { throw new Error('Folder scan cancelled; no selection changed.'); }
      if (++visited > limit) { throw new Error(`Folder scan exceeded ${limit} entries. Choose a narrower folder; no matches were selected.`); }
      const child = path.join(relative, entry.name);
      if (entry.isDirectory()) { pending.push(child); }
      else if (entry.isFile()) {
        const handle = await fs.promises.open(path.join(root, child), fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
        try {
          const magic = Buffer.alloc(4);
          const { bytesRead } = await handle.read(magic, 0, 4, 0);
          if (bytesRead === 4 && magic.equals(Buffer.from([0x7f, 0x45, 0x4c, 0x46]))) { candidates.push(child); }
        } finally { await handle.close(); }
      }
    }
  }
  return candidates.sort();
}

export function pairDigest(selection: FirmwareSelection, definition: string, digests: Record<R8Core, string>): string {
  return hash(JSON.stringify([selection.board, selection.group, definition, CORES.map((core) => [core, digests[core].toLowerCase()])]));
}

export class DualCoreLoaderController implements vscode.Disposable {
  private get preparing(): boolean { return this.store.isPreparingImages(); }
  private set preparing(active: boolean) { this.store.setImagePreparationActive(active); }
  private historyToken = 0;
  private disposed = false;
  private historyContext = '';
  private readonly registrations: vscode.Disposable[] = [];

  constructor(private readonly client: BackendClient, private readonly store: SelectionStore,
    private readonly execution: ExecutionController) {
    const actions: Record<string, (core?: R8Core) => Promise<unknown>> = {
      browse: (core) => this.pickSource(core, false), folder: (core) => this.pickSource(core, true),
      useBuild: (core) => this.useBuild(core), buildBoth: () => this.buildBoth(),
      validate: () => this.validate(), refresh: () => this.validate(), resume: () => this.resume(),
      keepCaptured: (core) => this.keepCaptured(core), importUpdated: (core) => this.importUpdated(core),
      loadBoth: () => this.targetAction('load'), recoverBoth: () => this.targetAction('recover'),
      debugR80: () => this.targetAction('debug', 'cr8_0'), debugR81: () => this.targetAction('debug', 'cr8_1'),
    };
    for (const [name, action] of Object.entries(actions)) {
      this.registrations.push(vscode.commands.registerCommand(`px4Nuttx.dual.${name}`, async (argument?: R8Core | { core?: R8Core; setupId?: string; token?: SetupOperationToken }) => {
        try { if (argument && typeof argument !== 'string' && ((argument.setupId && argument.setupId !== store.getActiveSetup()?.id) || (argument.token && !store.isSetupTokenCurrent(argument.token)))) { throw new Error('The clicked setup row changed. Refresh and choose again.'); } if (store.getActiveSetup()) { store.assertSetupOperationsReady(); } return await action(typeof argument === 'string' ? argument : argument?.core); }
        catch (error) { void vscode.window.showErrorMessage((error as Error).message); return false; }
      }));
    }
    this.registrations.push(store.onDidChangeSelection(() => {
      const state = store.getPreparedPair();
      const key = JSON.stringify([store.getActiveSetup()?.id, store.captureSetupToken().revision, store.getSelection().group, store.getSelectedProbe(), state?.generation,
        state?.prepared?.receiptId, store.getCatalog()?.capabilities?.targetHistory]);
      if (key !== this.historyContext) {
        this.historyContext = key;
        void this.refreshHistory().catch((error) => { if (!this.disposed) { void vscode.window.showErrorMessage(`Load history unavailable: ${(error as Error).message}`); } });
      }
    }));
  }

  private requireReady(capabilities: Array<'importImages' | 'preparedIdentity' | 'strictLoadedIdentity' | 'targetHistory'> = ['importImages'], owner?: symbol): FirmwareSelection {
    if (vscode.workspace.isTrusted === false) { throw new Error('Trust this workspace before preparing or using images.'); }
    this.store.assertMutable(owner);
    if (this.preparing) { throw new Error('Image preparation is in progress. Wait for it to finish.'); }
    const selection = this.store.getSelection();
    const group = this.store.getGroupMeta();
    if (selection.board !== 'rdk-rzv2h' || group?.loadRecipe !== 'rzv-dual-cr8-ram'
      || group.members.length !== 2 || !CORES.every((core) => group.members.some((member) => member.core === core))) {
      throw new Error('Select a catalogued RDK-RZ/V2H dual-CR8 group. RA8P1 and CM33 loading are unavailable here.');
    }
    const caps = this.store.getCatalog()?.capabilities;
    if (!caps?.receiptVersions?.includes(2) || capabilities.some((key) => caps[key] !== 1)) {
      throw new Error('This checkout backend does not support this Dual-Core Loader action. Update the extension and checkout together, then Refresh.');
    }
    return selection;
  }

  private async chooseCore(core?: R8Core, placeHolder = 'Choose the image row to update'): Promise<R8Core | undefined> {
    return core && CORES.includes(core) ? core : (await vscode.window.showQuickPick(CORES.map((value) => ({ label: value === 'cr8_0' ? 'R8-0' : 'R8-1', core: value })),
      { placeHolder }))?.core;
  }

  /**
   * Starts the backend-owned RTT bridge for one loaded core of the captured pair.
   * The backend reserves the probe for the bridge's lifetime, refuses a core the
   * last verified load did not leave ready, and marks the target for recovery when
   * the J-Link connect fails (a failed CR8 connect can reset the SoC). The bridge
   * serves 127.0.0.1:19021 for any terminal; the extension opens none itself.
   */
  public async startRtt(core?: R8Core): Promise<boolean> {
    const selection = this.requireReady(['importImages', 'preparedIdentity']);
    const token = this.store.captureSetupToken(undefined, true);
    core = await this.chooseCore(core, 'Choose the core whose RTT console to bridge');
    this.assertContext(token);
    if (!core) { return false; }
    const name = core === 'cr8_0' ? 'R8-0' : 'R8-1';
    const transport = this.store.getConsoleTransport(core);
    if (transport !== 'rtt') { throw new Error(`${name} uses ${transport.toUpperCase()}, not RTT. Open that UART in your own serial terminal.`); }
    const serial = this.store.getSelectedProbe();
    if (!serial) { throw new Error('Select a J-Link probe before starting the RTT bridge.'); }
    if (this.store.hasOwnedSessions()) { throw new Error('Stop the debug session first: the RTT bridge needs the probe.'); }
    if (!await this.validate()) { throw new Error('Images need attention. Validate and load this exact pair before starting the RTT bridge.'); }
    this.assertContext(token);
    const receiptPath = this.store.getPreparedPair()!.prepared!.receiptPath;
    const result = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `Starting ${name} RTT bridge` },
      () => this.client.consoleAction('start', this.store.writeSelectionSnapshot(selection), receiptPath, serial, { core }));
    if (result.status !== 'ok') {
      throw new Error(result.diagnostics.map((item) => item.message).join('; ') || `${name} RTT bridge did not start.`);
    }
    void vscode.window.showInformationMessage(`${name} RTT bridge is up on ${result.data?.endpoint || '127.0.0.1:19021'}. ` +
      'Connect a terminal such as μScope to it. Use Stop RTT Bridge before Load, Recover or Debug.');
    return true;
  }

  /**
   * Stops the RTT bridge this checkout's backend started; a manual bridge is not touched.
   * `quiet` (used by Stop Sessions) reports only a bridge that was actually stopped.
   */
  public async stopRtt(quiet = false): Promise<boolean> {
    if (vscode.workspace.isTrusted === false) { throw new Error('Trust this workspace before stopping the RTT bridge.'); }
    const serial = this.store.getSelectedProbe();
    if (!serial) { throw new Error('Select the J-Link probe whose RTT bridge to stop.'); }
    // The CLI requires both paths; stop reads neither, so an unprepared setup still stops.
    const receiptPath = this.store.getPreparedPair()?.prepared?.receiptPath || '';
    const result = await this.client.consoleAction('stop', this.store.writeSelectionSnapshot(this.store.getSelection()), receiptPath, serial);
    if (result.status !== 'ok') {
      throw new Error(result.diagnostics.map((item) => item.message).join('; ') || 'RTT bridge did not stop.');
    }
    if (result.data?.stopped) {
      void vscode.window.showInformationMessage('RTT bridge stopped; the probe is free.');
    } else if (!quiet) {
      void vscode.window.showInformationMessage('No extension-started RTT bridge was running. Stop a manual one with platforms/nuttx/Debug/nuttx-rtt-bridge.sh stop.');
    }
    return true;
  }

  public async pickSource(core?: R8Core, folder = false): Promise<void> {
    this.requireReady();
    const token = this.store.captureSetupToken(undefined, true);
    core = await this.chooseCore(core);
    this.assertContext(token);
    if (!core) { return; }
    const uris = await vscode.window.showOpenDialog({ canSelectFiles: !folder, canSelectFolders: folder, canSelectMany: false,
      title: folder ? `Choose build folder for ${core}` : `Browse ELF for ${core} (including suffixless nuttx)`, openLabel: 'Select' });
    if (!uris?.length) { return; }
    if (uris[0].scheme && !['file', 'vscode-remote'].includes(uris[0].scheme)) { throw new Error('Select a workspace-host filesystem path.'); }
    this.assertContext(token);
    const selectedPath = uris[0].fsPath;
    const member = this.store.getGroupMembers().find((item) => item.core === core)!;
    let source: ImageSource;
    if (folder) {
      const candidates = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: 'Finding ELF images', cancellable: true },
        (_, token) => scanElfCandidates(selectedPath, token));
      if (!candidates.length) { throw new Error('No ELF images found. Choose a different build folder.'); }
      const picked = await vscode.window.showQuickPick(candidates.map((relativePath) => ({ label: relativePath, description: selectedPath, relativePath })),
        { placeHolder: `Select the exact ${core} image; filenames do not establish core identity` });
      if (!picked) { return; }
      source = { kind: 'folder', path: selectedPath, relativePath: picked.relativePath, declaration: member };
    } else {
      source = { kind: 'file', path: await fs.promises.realpath(selectedPath), declaration: member };
    }
    const declaration = await vscode.window.showWarningMessage(
      `Declare this image as ${core}: ${member.target || member.config}. Address checks cannot prove its firmware identity or hardware qualification.`, 'Use Declared Image');
    if (declaration !== 'Use Declared Image') { return; }
    this.assertContext(token);
    await this.assign(core, source);
  }

  public async assign(core: R8Core, source: ImageSource): Promise<void> {
    const selection = this.requireReady();
    const current = this.store.getPreparedPair() || { generation: 0, sources: {} };
    const sources: FirmwareImport['sources'] = {};
    for (const other of CORES) {
      if (other !== core && current.prepared?.artifacts.some((artifact) => artifact.core === other)) {
        sources[other] = { kind: 'prepared-receipt', receiptPath: current.prepared.receiptPath, artifactCore: other };
      }
    }
    sources[core] = source;
    await this.prepare(selection, { generation: current.generation, sources: { [core]: source } }, sources, [core]);
  }

  private async prepare(selection: FirmwareSelection, requested: Pick<PreparedPairState, 'generation' | 'sources'>,
    sources: FirmwareImport['sources'], replacedCores: R8Core[], owner?: symbol, cancellationToken?: vscode.CancellationToken): Promise<void> {
    if (cancellationToken?.isCancellationRequested) { throw new Error('Firmware workflow cancelled.'); }
    const context = this.store.captureSetupToken();
    const request: FirmwareImport = { schemaVersion: 1, requestId: crypto.randomUUID(), selection, sources };
    let next: PreparedPairState | undefined;
    this.preparing = true;
    try {
      const saved = await this.store.updatePreparedPair(selection.group!, (current) => {
        if ((current?.generation || 0) !== requested.generation) { return undefined; }
        const base = current || { generation: 0, sources: {} };
        const sourceRecords = { ...base.sources };
        const acknowledged = { ...base.acknowledged };
        const sourceChanges = { ...base.sourceChanges };
        for (const core of replacedCores) {
          sourceRecords[core] = requested.sources[core];
          delete acknowledged[core]; delete sourceChanges[core];
        }
        next = { ...base, generation: base.generation + 1, sources: sourceRecords, acknowledged, sourceChanges,
          pending: { request, sourceDigest: hash(JSON.stringify(sources)) }, validationError: undefined, history: undefined };
        return next;
      }, context, owner);
      if (!saved) { throw new Error('The image selection changed before preparation could be saved. Select the image again.'); }
      await this.runPreparation(selection, next!, owner, cancellationToken);
    } finally { this.preparing = false; }
    if (!owner) { await this.refreshHistory(); }
  }

  public async resume(): Promise<void> {
    const selection = this.requireReady();
    const state = this.store.getPreparedPair();
    if (!state?.pending) { throw new Error('There is no pending preparation to resume.'); }
    await this.runPreparation(selection, state);
  }

  private async runPreparation(selection: FirmwareSelection, state: PreparedPairState, owner?: symbol, cancellationToken?: vscode.CancellationToken): Promise<void> {
    const context = this.store.captureSetupToken();
    this.preparing = true;
    try {
      const request = state.pending!.request;
      const directory = path.join(this.store.getWorkspaceRoot(), '.vscode');
      await fs.promises.mkdir(directory, { recursive: true });
      const file = path.join(directory, `${request.requestId}.firmware-import.json`);
      const content = JSON.stringify(request, null, 2);
      let existing: string | undefined;
      try { existing = await fs.promises.readFile(file, 'utf8'); }
      catch (error) { if ((error as NodeJS.ErrnoException).code !== 'ENOENT') { throw error; } }
      if (existing !== undefined && existing !== content) { throw new Error('Pending import input changed; start a new image selection.'); }
      if (existing === undefined) {
        const temporary = `${file}.tmp-${crypto.randomUUID()}`;
        try {
          const handle = await fs.promises.open(temporary, 'wx', 0o600);
          try { await handle.writeFile(content, 'utf8'); await handle.sync(); }
          finally { await handle.close(); }
          await fs.promises.rename(temporary, file);
        } finally { await fs.promises.unlink(temporary).catch(() => undefined); }
      }
      const result = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: 'Capturing and checking images', cancellable: !cancellationToken },
        (_, token) => {
          this.assertContext(context);
          return this.client.importImages(file, { cancellationToken: cancellationToken || token });
        });
      if (result.status !== 'ok' || !result.receiptPath) { throw new Error(result.diagnostics.map((item) => item.message).join('; ') || 'Preparation interrupted. Use Resume Preparation.'); }
      if (result.data.requestId !== request.requestId || result.data.receiptId !== `import-${request.requestId}`) { throw new Error('Importer returned a different preparation identity.'); }
      const receiptPath = this.store.resolveReceiptPath(result.receiptPath);
      const digests = Object.fromEntries(result.data.artifacts.map((item) => [item.core, item.sha256])) as Record<R8Core, string>;
      const prepared = { receiptPath, receiptId: result.data.receiptId, receiptSha256: await fileDigest(receiptPath),
        groupDefinitionSha256: result.data.groupDefinitionSha256, artifacts: result.data.artifacts,
        pairSha256: result.data.preparationState === 'ready' ? pairDigest(selection, result.data.groupDefinitionSha256, digests) : undefined };
      await this.store.updatePreparedPair(selection.group!, (current) => {
        if (this.disposed || !this.samePreparation(current, state)
          || current.pending?.request.requestId !== request.requestId
          || current.pending.sourceDigest !== state.pending!.sourceDigest) { return undefined; }
        return { ...current, pending: undefined, prepared, validationError: undefined };
      }, context, owner);
    } finally { this.preparing = false; }
  }

  public async validate(owner?: symbol): Promise<boolean> {
    const selection = this.requireReady(['importImages'], owner);
    const context = this.store.captureSetupToken();
    const state = this.store.getPreparedPair();
    if (!state?.prepared || state.pending) { throw new Error(state?.pending ? 'Resume the pending preparation first.' : 'Choose an image for each core.'); }
    const next = { ...state, sourceChanges: {}, validationError: undefined } as PreparedPairState;
    try {
      if (await fileDigest(state.prepared.receiptPath) !== state.prepared.receiptSha256) { throw new Error('Prepared receipt changed. Prepare images again.'); }
      if (state.prepared.groupDefinitionSha256 !== this.store.getGroupMeta()?.definitionSha256) { throw new Error('Group definition changed. Prepare images again.'); }
      for (const artifact of state.prepared.artifacts) {
        if (await fileDigest(this.store.resolveReceiptPath(artifact.path)) !== artifact.sha256) { throw new Error('Captured image changed. Prepare images again.'); }
        const core = artifact.core as R8Core;
        const original = artifact.sourceObservation;
        if (original) {
          const observed = await observeSource(original.path);
          if ((observed.sha256 !== original.sha256 || observed.size !== original.size || observed.mtimeNs !== original.mtimeNs)
            && state.acknowledged?.[core] !== JSON.stringify(observed)) {
            next.sourceChanges![core] = observed;
          }
        }
      }
    } catch (error) { next.validationError = (error as Error).message; }
    let ready = false;
    const saved = await this.store.updatePreparedPair(selection.group!, (current) => {
      if (this.disposed || this.preparing || this.store.getTargetTransition()
        || !this.samePreparation(current, state) || current.pending) { return undefined; }
      const changes = { ...next.sourceChanges };
      for (const core of CORES) {
        if (changes[core] && current.acknowledged?.[core] === JSON.stringify(changes[core])) { delete changes[core]; }
      }
      ready = !next.validationError && !Object.keys(changes).length && current.prepared?.artifacts.length === 2;
      return { ...current, sourceChanges: changes, validationError: next.validationError };
    }, context, owner);
    if (!saved) { return false; }
    if (!owner) { await this.refreshHistory(); }
    const current = this.store.getPreparedPair(selection.group);
    return ready && !this.preparing && this.samePreparation(current, state) && !current.pending
      && !current.validationError && !Object.keys(current.sourceChanges || {}).length;
  }

  public async keepCaptured(core?: R8Core): Promise<void> {
    const selection = this.requireReady();
    const context = this.store.captureSetupToken(undefined, true);
    core = await this.chooseCore(core);
    this.assertContext(context);
    const state = this.store.getPreparedPair();
    if (!core || !state?.sourceChanges?.[core] || state.validationError) { return; }
    const selectedCore = core;
    await this.store.updatePreparedPair(selection.group!, (current) => {
      if (this.preparing || !this.samePreparation(current, state) || current.validationError
        || JSON.stringify(current.sourceChanges?.[selectedCore]) !== JSON.stringify(state.sourceChanges![selectedCore])) { return undefined; }
      const changes = { ...current.sourceChanges }; delete changes[selectedCore];
      return { ...current, sourceChanges: changes, acknowledged: {
        ...current.acknowledged, [selectedCore]: JSON.stringify(state.sourceChanges![selectedCore]),
      } };
    });
  }

  public async importUpdated(core?: R8Core): Promise<void> {
    this.requireReady(); const token = this.store.captureSetupToken(undefined, true); core = await this.chooseCore(core); this.assertContext(token);
    const source = core && this.store.getPreparedPair()?.sources[core];
    if (core && source) { await this.assign(core, source); }
  }

  public async useBuild(core?: R8Core): Promise<void> {
    const selection = this.requireReady(); const token = this.store.captureSetupToken(undefined, true); core = await this.chooseCore(core); this.assertContext(token); if (!core) { return; }
    const directory = path.join(this.store.getWorkspaceRoot(), 'build', 'workspace-artifacts');
    const candidates: Array<{ label: string; description: string; receiptPath: string }> = [];
    for (const entry of await fs.promises.readdir(directory, { withFileTypes: true }).catch(() => [])) {
      if (!entry.isDirectory()) { continue; }
      const file = path.join(directory, entry.name, 'receipt.json');
      const receipt = this.store.readReceipt(file);
      const member = this.store.getGroupMembers().find((item) => item.core === core)!;
      if (receipt?.status === 'committed' && receipt.board === selection.board && receipt.operation !== 'import-images'
        && ((receipt.group === selection.group && receipt.groupDefinitionSha256 === this.store.getGroupMeta()?.definitionSha256)
          || (!receipt.group && receipt.core === core && receipt.family === member.family && (receipt.target || undefined) === member.target && (receipt.config || undefined) === member.config))) {
        candidates.push({ label: receipt.receiptId, description: file, receiptPath: file });
      }
    }
    if (!candidates.length) { throw new Error('No matching build receipts found. Build the selected group first.'); }
    const picked = await vscode.window.showQuickPick(candidates, { placeHolder: `Select the exact build receipt for ${core}` });
    this.assertContext(token);
    if (picked) { await this.assign(core, { kind: 'build-receipt', receiptPath: picked.receiptPath, artifactCore: core }); }
  }

  private assertContext(token: SetupOperationToken): void {
    if (this.disposed || !this.store.isSetupTokenCurrent(token) || vscode.workspace.isTrusted === false) { throw new Error('Firmware setup changed or closed; action cancelled.'); }
  }

  public async buildCore(core?: R8Core): Promise<void> {
    this.requireReady(); const token = this.store.captureSetupToken(undefined, true);
    core = await this.chooseCore(core); this.assertContext(token); if (!core) { return; }
    await this.buildWorkflow(core, false);
  }
  public async buildBoth(clean = false): Promise<void> { await this.buildWorkflow(undefined, false, clean); }
  public async buildAndLoad(): Promise<void> { await this.buildWorkflow(undefined, true); }

  private async buildWorkflow(core: R8Core | undefined, load: boolean, clean = false): Promise<void> {
    this.requireReady();
    const starting = this.store.captureSetupToken(undefined, true);
    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: load ? 'Build, capture and load firmware' : 'Build and capture firmware', cancellable: true }, async (_, cancellationToken) => {
      await this.store.withSetupMutationGuard(async (owner) => {
        this.assertContext(starting);
        const selection = this.requireReady(['importImages'], owner);
        const context = this.store.captureSetupToken();
        const before = this.store.getPreparedPair() || { generation: 0, sources: {} };
        const member = core && this.store.getGroupMembers().find((m) => m.core === core);
        const building: FirmwareSelection = member ? { schemaVersion: 1, id: `${selection.group}-${core}`, board: selection.board, core: member.core as R8Core,
          build: { family: member.family, mode: selection.build.mode, ...(member.target ? { target: member.target } : { config: member.config }) } } : selection;
        const result = this.execution.buildExact
          ? await this.execution.buildExact(building, clean, cancellationToken)
          : await this.execution.buildSelectedGroup(building);
        this.assertContext(context);
        if (cancellationToken.isCancellationRequested || result?.status !== 'ok' || !result.receiptPath) { return; }
        if ((this.store.getPreparedPair()?.generation || 0) !== before.generation) { throw new Error('Images changed during the build; its output was not adopted.'); }
        const receiptPath = this.store.resolveReceiptPath(result.receiptPath);
        const receipt = this.store.readReceipt(receiptPath);
        if (!receipt || receipt.status !== 'committed' || receipt.selectionId !== building.id || receipt.board !== selection.board
          || (core ? receipt.core !== core || receipt.family !== member!.family || (receipt.target || undefined) !== member!.target || (receipt.config || undefined) !== member!.config
            : receipt.group !== selection.group || receipt.groupDefinitionSha256 !== this.store.getGroupMeta()?.definitionSha256)) {
          throw new Error('Build returned an incompatible receipt; images were not adopted.');
        }
        const expectedCores = core ? [core] : CORES;
        if (!Array.isArray(receipt.artifacts) || receipt.artifacts.length !== expectedCores.length || expectedCores.some((key) => receipt.artifacts.filter((artifact: { core: string }) => artifact.core === key).length !== 1)) { throw new Error('Build receipt is incomplete or has duplicate/unexpected cores.'); }
        for (const artifact of receipt.artifacts) {
          const file = this.store.resolveReceiptPath(artifact.path);
          if ((await fs.promises.stat(file)).size !== artifact.size || await fileDigest(file) !== artifact.sha256) { throw new Error('Built artifact changed before capture.'); }
        }
        this.assertContext(context);
        const sources: FirmwareImport['sources'] = {};
        const records = { ...before.sources };
        for (const key of CORES) {
          if (!core || key === core) { sources[key] = { kind: 'build-receipt', receiptPath, artifactCore: key }; records[key] = sources[key]; }
          else if (before.prepared?.artifacts.some((a) => a.core === key)) {
            sources[key] = { kind: 'prepared-receipt', receiptPath: before.prepared.receiptPath, artifactCore: key };
          }
        }
        await this.prepare(selection, { generation: before.generation, sources: records }, sources, core ? [core] : CORES, owner, cancellationToken);
        this.assertContext(context);
        if (load && !cancellationToken.isCancellationRequested) { await this.targetAction('load', undefined, owner, cancellationToken); }
      });
    });
    await this.refreshHistory();
  }

  public async loadAndDebug(): Promise<boolean> {
    const starting = this.store.captureSetupToken(undefined, true);
    const core = this.store.getSelectedCore() as R8Core;
    const result = await this.store.withSetupMutationGuard(async (owner) => { this.assertContext(starting); return this.targetAction('loadAndDebug', core, owner); });
    await this.refreshHistory(); return result;
  }

  public async targetAction(action: 'load' | 'recover' | 'debug' | 'loadAndDebug', core?: R8Core, owner?: symbol, cancellationToken?: vscode.CancellationToken): Promise<boolean> {
    const selection = this.requireReady(['debug', 'loadAndDebug'].includes(action) ? ['importImages', 'preparedIdentity', 'strictLoadedIdentity'] : ['importImages', 'preparedIdentity'], owner);
    const context = this.store.captureSetupToken();
    if (!await this.validate(owner)) { throw new Error('Images need attention. Resolve source changes or validation errors before loading/debugging.'); }
    this.assertContext(context);
    if (cancellationToken?.isCancellationRequested) { return false; }
    const state = this.store.getPreparedPair()!;
    const prepared = state.prepared!;
    const request: PreparedExecutionRequest = { setupToken: context, workflowOwner: owner, workflowCancellation: cancellationToken, selection, selectionPath: this.store.writeSelectionSnapshot(selection),
      receiptPath: prepared.receiptPath, receiptId: prepared.receiptId, pairGeneration: state.generation,
      groupDefinitionSha256: prepared.groupDefinitionSha256, pairSha256: prepared.pairSha256!,
      operationInstanceId: crypto.randomUUID(), artifactDigests: Object.fromEntries(prepared.artifacts.map((item) => [item.core, item.sha256])) as Record<R8Core, string>,
      serial: this.store.getSelectedProbe() };
    ++this.historyToken;
    if (action === 'loadAndDebug') {
      if (!core || !CORES.includes(core)) { throw new Error('Choose a concrete CR8 member before loading and debugging.'); }
      const lease = await this.client.probeLeases.acquire(request.serial);
      let transferred = false;
      try {
        this.assertContext(context);
        const loaded = await this.execution.loadPrepared(request, { recover: false, allowImplicitBuild: false, retainedLease: lease });
        if (loaded?.status !== 'ok') { return false; }
        this.assertContext(context);
        transferred = await this.execution.debugPrepared(request, core, { requireLoaded: true, retainedLease: lease });
        return transferred;
      } finally { if (!transferred) { await lease.release(); } }
    }
    const result = action === 'debug'
      ? await this.execution.debugPrepared(request, core!, { requireLoaded: true })
      : (await this.execution.loadPrepared(request, { recover: action === 'recover', allowImplicitBuild: false }))?.status === 'ok';
    if (!owner) { await this.refreshHistory(); }
    return result;
  }

  public async refreshHistory(): Promise<void> {
    if (this.disposed || this.store.hasWorkflow() || vscode.workspace.isTrusted === false || this.store.getCatalog()?.capabilities?.targetHistory !== 1) { return; }
    const selection = this.store.getSelection(); const state = this.store.getPreparedPair(); const serial = this.store.getSelectedProbe();
    if (!state?.prepared || state.pending || this.preparing || !serial) { return; }
    const context = this.store.captureSetupToken();
    const token = ++this.historyToken;
    const result = await this.client.runDoctor(undefined, { serial });
    const history = result.data?.targetHistory;
    const verified = !!state.prepared.pairSha256 && history?.verifiedPair?.pairSha256 === state.prepared.pairSha256
      && history.verifiedPair.groupDefinitionSha256 === state.prepared.groupDefinitionSha256
      && state.prepared.artifacts.every((artifact) => history.verifiedPair?.artifactDigests[artifact.core as R8Core] === artifact.sha256)
      && history?.recoveryRequired === false;
    await this.store.updatePreparedPair(selection.group!, (current) => {
      if (this.disposed || token !== this.historyToken || !this.samePreparation(current, state)
        || !!this.store.getTargetTransition() || this.preparing || current.pending
        || serial !== this.store.getSelectedProbe() || selection.group !== this.store.getSelection().group) { return undefined; }
      return { ...current, history: { verified,
        message: verified ? 'Last load verified' : history?.recoveryRequired ? 'Recover Both required' : 'Load Both required', timestamp: history?.verifiedPair?.timestamp } };
    }, context);
  }

  private samePreparation(current: PreparedPairState | undefined, expected: PreparedPairState): current is PreparedPairState {
    return !!current && current.generation === expected.generation
      && current.pending?.request.requestId === expected.pending?.request.requestId
      && current.prepared?.receiptId === expected.prepared?.receiptId
      && current.prepared?.receiptSha256 === expected.prepared?.receiptSha256;
  }

  public dispose(): void { this.disposed = true; ++this.historyToken; for (const registration of this.registrations) { registration.dispose(); } }
}
