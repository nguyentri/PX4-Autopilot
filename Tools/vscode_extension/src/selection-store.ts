import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import {
  CatalogData,
  ConsoleTransport,
  CoreCapability,
  FirmwareOperation,
  FirmwareSelection,
  GroupMetadata,
  SelectionCapabilities,
  PreparedPairState, SavedFirmwareSetup, SetupOperationToken,
} from './types';

import { FolderState, decodeFolderState, validSelection } from './setup-state';

const SELECTION_STATE_KEY = 'px4Nuttx.folderState';
const DEFAULT_SELECTION: FirmwareSelection = {
  schemaVersion: 1,
  id: 'rzv2h-simple',
  board: 'rdk-rzv2h',
  core: 'cr8_0',
  build: {
    family: 'px4',
    target: 'renesas_rdk-rzv2h_simple',
    mode: 'incremental',
  },
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function selectionKey(selection: FirmwareSelection): string {
  const payload = {
    id: selection.id,
    board: selection.board,
    core: selection.core,
    group: selection.group || null,
    build: selection.build,
    load: selection.load || null,
    debug: selection.debug || null,
  };
  return crypto.createHash('sha256').update(JSON.stringify(payload)).digest('hex');
}

function trusted(): boolean {
  return vscode.workspace?.isTrusted !== false;
}

export class SelectionStore implements vscode.Disposable {
  private readonly _onDidChangeSelection = new vscode.EventEmitter<FirmwareSelection>();
  public readonly onDidChangeSelection = this._onDidChangeSelection.event;

  private state: FolderState;
  private readonly stateError?: string;
  private catalog: CatalogData | null = null;
  private persistence?: Promise<void>;
  private pendingWrites = 0;
  private targetTransition = '';
  private workflowOwner?: symbol;
  private closed = false;
  private canonicalLoaded: boolean;
  private consoleStatus: (core: string) => string | undefined = () => undefined;
  public setConsoleStatusProvider(provider: (core: string) => string | undefined): void { this.consoleStatus = provider; }
  public getConsoleStatus(core: string): string | undefined { return this.consoleStatus(core); }
  private sessionGuard: () => boolean = () => false;
  private compatibilityWarning = '';
  private setupOperationsReady = false;

  constructor(private readonly context: vscode.ExtensionContext, private readonly workspaceRoot: string) {
    const decoded = decodeFolderState(context.workspaceState.get(this.canonicalKey()), context.workspaceState.get(this.stateKey()));
    this.state = decoded.state; this.stateError = decoded.error; this.canonicalLoaded = decoded.canonical;
    if (!this.state.activeSetupId) { this.state.selection = this.loadInitialSelection(this.state); }
    if (decoded.canonical && !decoded.error && JSON.stringify(context.workspaceState.get(this.stateKey())) !== JSON.stringify(this.legacyProjection(this.state))) {
      this.compatibilityWarning = 'Compatibility projection needs synchronization before downgrade.';
    }
  }

  private get activeSelection(): FirmwareSelection { return this.state.selection || DEFAULT_SELECTION; }
  private get selectedCore(): string { return this.state.selectedCore || ''; }
  private get selectedProbeSerial(): string { return this.state.selectedProbeSerial || ''; }
  private get receiptBindings(): FolderState['receipts'] { return this.state.receipts; }
  public getWorkspaceRoot(): string { return this.workspaceRoot; }
  private stateKey(): string { return `${SELECTION_STATE_KEY}.${this.workspaceRoot}`; }
  private canonicalKey(): string { return `${this.stateKey()}.setups.v2`; }
  public getStateError(): string | undefined { return this.stateError; }
  public getCompatibilityWarning(): string { return this.compatibilityWarning; }
  public hasPendingPersistence(): boolean { return this.pendingWrites > 0; }
  public async flushPersistence(): Promise<void> { await this.persistence; }
  public setSessionGuard(guard: () => boolean): void { this.sessionGuard = guard; }
  public notifySessionChange(): void { this._onDidChangeSelection.fire(this.getSelection()); }
  public hasOwnedSessions(): boolean { return this.sessionGuard(); }
  public setSetupOperationsReady(ready: boolean): void { this.setupOperationsReady = ready; this.notifySessionChange(); }
  public isSetupOperationsReady(): boolean { return this.setupOperationsReady; }
  public hasWorkflow(): boolean { return !!this.workflowOwner; }
  public assertSetupOperationsReady(): void {
    if (!this.setupOperationsReady) { throw new Error('Firmware Setup actions are not ready. Finish workspace initialization first.'); }
  }

  private enqueuePersistence<T>(write: () => Promise<T>): Promise<T> {
    this.pendingWrites++;
    const run = async () => { try { return await write(); } finally { this.pendingWrites--; } };
    const next = this.persistence ? this.persistence.then(run) : run();
    const tail = next.then(() => undefined, () => undefined);
    this.persistence = tail;
    void tail.then(() => { if (this.persistence === tail) { this.persistence = undefined; } });
    return next;
  }

  private legacyProjection(state: FolderState): object {
    const assignments = clone(state.imageAssignments);
    for (const setup of Object.values(state.setups)) {
      const group = setup.selection.group!;
      if (setup.pair && !assignments[group]) { assignments[group] = clone(setup.pair); }
    }
    const active = state.activeSetupId && state.setups[state.activeSetupId];
    if (active && active.pair) { assignments[active.selection.group!] = clone(active.pair); }
    return { selection: state.selection, selectedProbeSerial: state.selectedProbeSerial,
      selectedCore: state.selectedCore, receipts: state.receipts, imageAssignments: assignments };
  }

  private transact(reducer: (next: FolderState) => boolean | void, token?: SetupOperationToken, owner?: symbol): Promise<boolean> {
    return this.enqueuePersistence(async () => {
      if (this.closed || !trusted()) { throw new Error('Workspace trust and an active extension are required to save firmware state.'); }
      if (this.stateError) { throw new Error(this.stateError); }
      if (token && !this.isSetupTokenCurrent(token)) { return false; }
      const next = clone(this.state);
      if (reducer(next) === false) { return false; }
      this.assertMutable(owner);
      await this.context.workspaceState.update(this.canonicalKey(), next);
      if (this.closed || !trusted()) { return false; }
      this.state = next; this.canonicalLoaded = true;
      try {
        if (!trusted() || this.closed) { throw new Error('Workspace stopped before compatibility projection was saved.'); }
        await this.context.workspaceState.update(this.stateKey(), this.legacyProjection(next));
        this.compatibilityWarning = '';
      } catch (error) { this.compatibilityWarning = `Saved setups are durable; retry compatibility projection before downgrading: ${(error as Error).message}`; }
      this._onDidChangeSelection.fire(this.getSelection());
      return true;
    });
  }

  private supportedGroup(selection: FirmwareSelection): boolean {
    const group = selection.group && this.catalog?.groups[selection.group];
    return !!group && group.board === 'rdk-rzv2h' && group.loadRecipe === 'rzv-dual-cr8-ram'
      && group.members.length === 2 && group.members.some((m) => m.core === 'cr8_0') && group.members.some((m) => m.core === 'cr8_1');
  }

  private selectInState(next: FolderState, selection: FirmwareSelection): void {
    next.activeSetupId = undefined;
    if (this.supportedGroup(selection)) {
      const id = `group:${selection.group}`;
      next.setups[id] ||= { id, name: this.catalog!.groups[selection.group!].name || selection.group!, selection: clone(selection),
        pair: next.imageAssignments[selection.group!], selectedCore: ['cr8_0', 'cr8_1'].includes(next.selectedCore || '') ? next.selectedCore : undefined };
      next.activeSetupId = id;
      next.selection = clone(next.setups[id].selection);
      next.selectedCore = next.setups[id].selectedCore || this.catalog!.groups[selection.group!].members[0].core;
    } else { next.selection = clone(selection); next.selectedCore = selection.core === 'multicore' ? '' : selection.core; }
    next.revision++;
  }

  public async initialize(): Promise<void> {
    if (!trusted() || this.closed || this.stateError) { return; }
    await this.transact((next) => {
      let changed = !this.canonicalLoaded || !!this.compatibilityWarning;
      for (const [group, pair] of Object.entries(next.imageAssignments)) {
        const meta = this.catalog?.groups[group];
        if (!meta || meta.board !== 'rdk-rzv2h' || meta.loadRecipe !== 'rzv-dual-cr8-ram' || next.setups[`group:${group}`]) { continue; }
        const selection: FirmwareSelection = next.selection?.group === group ? clone(next.selection) : pair.pending?.request.selection.group === group ? clone(pair.pending.request.selection) : { schemaVersion: 1, id: group, board: 'rdk-rzv2h', core: 'multicore', group,
          build: { family: meta.family || meta.members[0].family, mode: 'incremental' }, load: { recipe: meta.loadRecipe }, debug: { mode: 'attach' } };
        if (!this.supportedGroup(selection)) { continue; }
        next.setups[`group:${group}`] = { id: `group:${group}`, name: meta.name || group, selection, pair: clone(pair) }; changed = true;
      }
      if (!next.activeSetupId && next.selection && this.supportedGroup(next.selection)) { this.selectInState(next, next.selection); changed = true; }
      return changed;
    });
  }

  public listSavedSetups(): SavedFirmwareSetup[] { return clone(Object.values(this.state.setups)); }
  public getActiveSetup(): SavedFirmwareSetup | undefined {
    const value = this.state.activeSetupId && this.state.setups[this.state.activeSetupId];
    return value ? clone(value) : undefined;
  }
  private assertSessionMutable(): void {
    if (this.sessionGuard()) { throw new Error('Stop Sessions before changing the setup, core, probe or console device.'); }
  }
  public captureSetupToken(core?: string, includePair = false): SetupOperationToken {
    return { setupId: this.state.activeSetupId, revision: this.state.revision,
      selectionIdentity: this.getSelectionIdentity(), definition: this.getGroupMeta()?.definitionSha256,
      ...(includePair ? { pairGeneration: this.getPreparedPair()?.generation || 0 } : {}),
      probe: this.getSelectedProbe(), core, device: core ? this.getConsoleDevice(core) : undefined };
  }
  public isSetupTokenCurrent(token: SetupOperationToken): boolean {
    const now = this.captureSetupToken(token.core, Object.prototype.hasOwnProperty.call(token, 'pairGeneration'));
    return !this.closed && JSON.stringify(token) === JSON.stringify(now);
  }
  public async activateSetup(id: string): Promise<void> {
    this.assertSessionMutable();
    await this.transact((next) => {
      this.assertSessionMutable();
      const setup = next.setups[id];
      if (!setup || !this.supportedGroup(setup.selection)) { throw new Error('The saved setup group is unavailable. Refresh its catalog.'); }
      next.activeSetupId = id; next.selection = clone(setup.selection); next.selectedCore = setup.selectedCore || '';
      next.revision++;
    });
  }
  private setupName(name: string, ignoreId?: string): string {
    const value = name.trim();
    if (!value || value.length > 128 || /[\x00-\x1f\x7f]/.test(value)) { throw new Error('Enter a setup name of 1–128 printable characters.'); }
    if (this.listSavedSetups().some((s) => s.id !== ignoreId && s.name.toLowerCase() === value.toLowerCase())) { throw new Error('A setup already has that name.'); }
    return value;
  }
  public async saveActiveSetupAs(name: string): Promise<void> {
    this.assertMutable();
    if (this.pendingWrites) { throw new Error('Wait for image preparation and saving to finish before Save As.'); }
    const label = this.setupName(name); this.assertSessionMutable();
    await this.transact((next) => {
      this.assertSessionMutable(); const active = next.activeSetupId && next.setups[next.activeSetupId];
      if (!active || active.pair?.pending) { throw new Error('Finish or Resume Preparation before saving a setup variant.'); }
      this.setupName(label);
      const id = crypto.randomUUID(); next.setups[id] = { ...clone(active), id, name: label };
      next.activeSetupId = id; next.revision++;
    });
  }
  public async renameSetup(name: string): Promise<void> {
    const label = this.setupName(name, this.state.activeSetupId);
    await this.transact((next) => { if (!next.activeSetupId) { throw new Error('Select a saved setup.'); } this.setupName(label, next.activeSetupId); next.setups[next.activeSetupId].name = label; });
  }
  public async setBuildMode(mode: 'clean' | 'incremental'): Promise<void> {
    this.assertSessionMutable();
    await this.transact((next) => {
      this.assertSessionMutable(); next.selection!.build.mode = mode;
      if (next.activeSetupId) { next.setups[next.activeSetupId].selection.build.mode = mode; }
      next.revision++;
    });
  }
  public getConsoleDevice(core: string): string {
    return this.getActiveSetup()?.consoleDevices?.[core]
      || vscode.workspace.getConfiguration('px4Nuttx', vscode.Uri?.file?.(this.workspaceRoot)).get<string>('consolePort', '');
  }
  public async setSetupConsoleDevice(core: string, device: string): Promise<void> {
    this.assertSessionMutable();
    if (!device || /[\x00-\x1f\x7f]/.test(device) || device.includes('://')) { throw new Error('Select a workspace-host serial device path.'); }
    await this.transact((next) => {
      this.assertSessionMutable(); const setup = next.activeSetupId && next.setups[next.activeSetupId];
      if (!setup || !['cr8_0', 'cr8_1'].includes(core)) { throw new Error('Select a supported saved setup/core.'); }
      setup.consoleDevices ||= {}; setup.consoleDevices[core] = device; next.revision++;
    });
  }

  public getPreparedPair(group = this.activeSelection.group): PreparedPairState | undefined {
    const active = this.getActiveSetup();
    const pair = active && active.selection.group === group ? active.pair : group ? this.state.setups[`group:${group}`]?.pair || this.state.imageAssignments[group] : undefined;
    return pair ? clone(pair) : undefined;
  }
  public async setPreparedPair(group: string, value: PreparedPairState): Promise<void> { await this.updatePreparedPair(group, () => value); }
  public updatePreparedPair(group: string, update: (current: PreparedPairState | undefined) => PreparedPairState | undefined,
    token = this.captureSetupToken(), owner?: symbol): Promise<boolean> {
    return this.transact((next) => {
      const value = update(this.getPreparedPair(group)); if (!value) { return false; }
      const setup = next.activeSetupId && next.setups[next.activeSetupId];
      if (setup && setup.selection.group === group) { setup.pair = clone(value); }
      else { next.imageAssignments[group] = clone(value); }
      return true;
    }, token, owner);
  }
  public async withSetupMutationGuard<T>(run: (owner: symbol) => Promise<T>): Promise<T> {
    this.assertMutable(); await this.flushPersistence(); this.assertMutable();
    const owner = Symbol('firmware workflow'); this.workflowOwner = owner; this.notifySessionChange();
    try { return await run(owner); } finally { if (this.workflowOwner === owner) { this.workflowOwner = undefined; this.notifySessionChange(); } }
  }
  public getTargetTransition(): string { return this.targetTransition; }
  public beginTargetTransition(label: string, owner?: symbol): void {
    this.assertMutable(owner);
    if (this.pendingWrites) { throw new Error('Saving image selection: wait before starting a target operation.'); }
    this.targetTransition = label;
    this._onDidChangeSelection.fire(this.getSelection());
  }
  public endTargetTransition(): void { this.targetTransition = ''; this._onDidChangeSelection.fire(this.getSelection()); }
  public assertMutable(owner?: symbol): void {
    if (this.closed || this.stateError) { throw new Error(this.stateError || 'Firmware workspace is shutting down.'); }
    if (this.targetTransition) { throw new Error(`${this.targetTransition}: wait for the target operation to finish.`); }
    if (this.workflowOwner && this.workflowOwner !== owner) { throw new Error('Firmware workflow in progress; wait or cancel it before changing inputs.'); }
  }

  private loadInitialSelection(saved: FolderState): FirmwareSelection {
    const customConfig = path.join(this.workspaceRoot, '.vscode', 'firmware-workspace.json');
    if (fs.existsSync(customConfig)) {
      try {
        const parsed = JSON.parse(fs.readFileSync(customConfig, 'utf-8')) as FirmwareSelection;
        if (validSelection(parsed)) {
          return clone(parsed);
        }
      } catch {
        // Fall back to the per-folder workspace state.
      }
    }

    if (saved.selection && saved.selection.schemaVersion === 1) {
      return clone(saved.selection);
    }
    return clone(DEFAULT_SELECTION);
  }

  public getSelection(): FirmwareSelection {
    return clone(this.activeSelection);
  }

  public getSelectedProbe(): string {
    const configuration = vscode.Uri?.file
      ? vscode.workspace.getConfiguration('px4Nuttx', vscode.Uri.file(this.workspaceRoot))
      : vscode.workspace.getConfiguration('px4Nuttx');
    const fromConfig = configuration.get<string>('jlinkSerial', '');
    return fromConfig || this.selectedProbeSerial;
  }

  public getSelectedCore(): string {
    if (this.activeSelection.core !== 'multicore') {
      return this.activeSelection.core;
    }
    return this.selectedCore || this.getGroupMembers()[0]?.core || 'multicore';
  }

  public async setSelectedCore(core: string): Promise<void> {
    this.assertSessionMutable();
    await this.transact((next) => {
      this.assertSessionMutable();
      if (this.activeSelection.core !== 'multicore' || !this.getGroupMembers().some((m) => m.core === core)) { throw new Error(`Core ${core} is not a member of the selected firmware group.`); }
      next.selectedCore = core; if (next.activeSetupId) { next.setups[next.activeSetupId].selectedCore = core; } next.revision++;
    });
  }
  public async setSelection(selection: FirmwareSelection): Promise<void> {
    this.assertSessionMutable();
    if (!validSelection(selection)) { throw new Error('Invalid firmware selection.'); }
    await this.transact((next) => { this.assertSessionMutable(); this.selectInState(next, selection); });
    if (this.closed) { return; }
    await this.refreshReceipts();
    if (trusted() && !this.closed) { this.ensureSelectionFileOnDisk(); }
  }
  public async setSelectedProbe(serial: string): Promise<void> {
    this.assertSessionMutable();
    if (/[\x00-\x1f\x7f]/.test(serial)) { throw new Error('Invalid probe serial.'); }
    await this.transact((next) => { this.assertSessionMutable(); next.selectedProbeSerial = serial.trim(); next.revision++; });
  }

  public getSelectionFilePath(): string {
    return path.join(this.workspaceRoot, '.vscode', 'active-selection.json');
  }

  /** Write only at an explicit, trusted operation boundary. */
  public ensureSelectionFileOnDisk(): string {
    const file = this.getSelectionFilePath();
    if (!trusted() || this.closed) {
      return file;
    }
    this.writeJsonAtomically(file, this.activeSelection);
    return file;
  }

  /**
   * Freeze a selection for one task/operation. The filename is content
   * addressed, so a later profile change cannot mutate the process input.
   */
  public writeSelectionSnapshot(selection: FirmwareSelection = this.activeSelection): string {
    if (!trusted() || this.closed) {
      throw new Error('Workspace trust and an active extension are required before writing a selection snapshot.');
    }
    const id = selectionKey(selection);
    const file = path.join(this.workspaceRoot, '.vscode', `firmware-selection-${id}.json`);
    if (!fs.existsSync(file)) {
      this.writeJsonAtomically(file, selection);
    } else {
      let existing: FirmwareSelection;
      try {
        existing = JSON.parse(fs.readFileSync(file, 'utf-8')) as FirmwareSelection;
      } catch (error) {
        throw new Error(`Selection snapshot is unreadable: ${(error as Error).message}`);
      }
      if (JSON.stringify(existing) !== JSON.stringify(selection)) {
        throw new Error(`Selection snapshot was modified after publication: ${file}`);
      }
    }
    return file;
  }

  private writeJsonAtomically(file: string, value: unknown): void {
    const dir = path.dirname(file);
    fs.mkdirSync(dir, { recursive: true });
    const temporary = `${file}.tmp-${process.pid}`;
    fs.writeFileSync(temporary, JSON.stringify(value, null, 2), 'utf-8');
    fs.renameSync(temporary, file);
  }

  public getSelectionIdentity(selection: FirmwareSelection = this.activeSelection): string {
    return selectionKey(selection);
  }

  public getReceiptPath(selection: FirmwareSelection = this.activeSelection): string | null {
    const pinned = this.getPreparedPair(selection.group)?.prepared;
    if (selection.group && pinned) {
      return this.receiptMatchesSelection(pinned.receiptPath, selection) ? pinned.receiptPath : null;
    }
    const binding = this.receiptBindings[selectionKey(selection)];
    if (!binding || !this.receiptMatchesSelection(binding.path, selection)) {
      return null;
    }
    return binding.path;
  }

  public async setReceiptPath(receiptPath: string | null, selection: FirmwareSelection = this.activeSelection): Promise<void> {
    const key = selectionKey(selection);
    const receipt = receiptPath && this.readReceipt(receiptPath);
    if (receiptPath && (!receipt || receipt.selectionId !== selection.id || receipt.status !== 'committed')) { return; }
    await this.transact((next) => {
      if (!receiptPath) { delete next.receipts[key]; }
      else { next.receipts[key] = { path: receiptPath, receiptId: receipt.receiptId }; }
    });
  }

  public readReceipt(receiptPath: string): any | null {
    const absolute = path.isAbsolute(receiptPath) ? receiptPath : path.join(this.workspaceRoot, receiptPath);
    try {
      return JSON.parse(fs.readFileSync(absolute, 'utf-8'));
    } catch {
      return null;
    }
  }

  public resolveReceiptPath(receiptPath: string): string {
    return path.isAbsolute(receiptPath) ? receiptPath : path.join(this.workspaceRoot, receiptPath);
  }

  /** Reconcile external CLI/task builds using the same identity as commands. */
  public async refreshReceipts(): Promise<void> {
    if (!trusted() || this.closed) {
      return;
    }
    if (this.getActiveSetup()) { return; }
    const root = path.join(this.workspaceRoot, 'build', 'workspace-artifacts');
    const candidates: Array<{ file: string; timestamp: number }> = [];
    try {
      for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
        if (!entry.isDirectory() || entry.name.startsWith('.')) {
          continue;
        }
        const file = path.join(root, entry.name, 'receipt.json');
        if (this.receiptMatchesSelection(file, this.activeSelection)) {
          const receipt = this.readReceipt(file);
          candidates.push({ file, timestamp: Date.parse(receipt.timestamp) || fs.statSync(file).mtimeMs });
        }
      }
    } catch {
      // No staged output is a normal first-run state. The bound receipt is
      // revalidated on every read, including after deletion/replacement.
    }
    candidates.sort((left, right) => right.timestamp - left.timestamp);
    if (candidates.length) {
      await this.setReceiptPath(path.relative(this.workspaceRoot, candidates[0].file));
    }
  }

  private receiptMatchesSelection(receiptPath: string, selection: FirmwareSelection): boolean {
    const receipt = this.readReceipt(receiptPath);
    if (!receipt || ![1, 2].includes(receipt.schemaVersion) || receipt.status !== 'committed' || receipt.selectionId !== selection.id
      || !Array.isArray(receipt.artifacts) || !receipt.artifacts.length
      || !receipt.artifacts.every((artifact: any) => typeof artifact.path === 'string'
        && typeof artifact.sha256 === 'string' && /^[a-fA-F0-9]{64}$/.test(artifact.sha256)
        && Number.isInteger(artifact.size) && artifact.size >= 0)) {
      return false;
    }
    if (receipt.board !== selection.board) {
      return false;
    }
    if (selection.group) {
      const expectedDefinition = this.catalog?.groups[selection.group]?.definitionSha256;
      return receipt.group === selection.group
        && receipt.core === 'multicore'
        && receipt.family === selection.build.family
        && !!expectedDefinition
        && receipt.groupDefinitionSha256 === expectedDefinition;
    }
    if (receipt.core !== selection.core || receipt.family !== selection.build.family) {
      return false;
    }
    if (selection.build.family === 'px4') {
      return receipt.target === selection.build.target;
    }
    return receipt.config === selection.build.config;
  }

  public setCatalog(catalog: CatalogData): void {
    this.catalog = catalog;
    if (trusted() && !this.closed && !this.stateError) { void this.initialize().then(() => this.refreshReceipts()).catch(() => undefined); }
    this._onDidChangeSelection.fire(this.getSelection());
  }

  public getCatalog(): CatalogData | null {
    return this.catalog;
  }

  public getGroupMeta(): GroupMetadata | undefined {
    const group = this.activeSelection.group;
    if (!group) {
      return undefined;
    }
    return this.catalog?.groups[group];
  }

  public getGroupMembers(): GroupMetadata['members'] {
    return this.getGroupMeta()?.members || [];
  }

  public getConsoleTransport(core: string = this.getSelectedCore()): ConsoleTransport {
    const groupTransport = this.getGroupMeta()?.console?.[core];
    if (groupTransport) {
      return groupTransport;
    }
    if (this.activeSelection.build.family === 'nuttx' && this.activeSelection.build.config) {
      const manifestPath = path.join(this.workspaceRoot, 'platforms', 'nuttx', 'Debug', 'rzv2h-all-sample-configs.json');
      try {
        const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf-8')) as { profiles?: Array<{ profile: string; console?: string }> };
        const profile = manifest.profiles?.find((entry) => entry.profile === this.activeSelection.build.config);
        if (profile?.console) {
          return profile.console as ConsoleTransport;
        }
      } catch {
        // An absent manifest leaves the console unavailable until the catalog is refreshed.
      }
      return 'none';
    }
    const capability = this.getCoreCapability(this.activeSelection.board, core);
    if (capability?.console) {
      return capability.console;
    }
    return this.activeSelection.board === 'rdk-rzv2h' && (core === 'cr8_0' || core === 'cr8_1')
      ? 'rtt'
      : 'none';
  }

  public getCapabilities(operation?: FirmwareOperation, core = this.getSelectedCore()): SelectionCapabilities {
    const group = this.getGroupMeta();
    const members = group?.members || [];
    const selectedMembers = group ? members : [{ core, family: this.activeSelection.build.family as 'px4' | 'nuttx' }];
    const capabilities = selectedMembers.map((member) => this.getCoreCapability(this.activeSelection.board, member.core));
    const validCapabilities = capabilities.filter((capability): capability is CoreCapability => !!capability);
    const has = (field: 'buildAvailable' | 'loadAvailable' | 'debugAvailable'): boolean =>
      selectedMembers.length > 0 && validCapabilities.length === selectedMembers.length && validCapabilities.every((capability) => capability[field]);

    const transport = this.getConsoleTransport(core);
    const managedRtt = this.activeSelection.board === 'rdk-rzv2h'
      && (core === 'cr8_0' || core === 'cr8_1')
      && transport === 'rtt';
    const reasons = validCapabilities.flatMap((capability) => capability.reasons || []);
    if (transport === 'rtt' && !managedRtt) {
      reasons.push('Managed RTT console ownership is admitted only for RDK-RZ/V2H CR8 cores.');
    }
    const result: SelectionCapabilities = {
      build: has('buildAvailable'),
      load: has('loadAvailable'),
      debug: has('debugAvailable'),
      console: validCapabilities.length === selectedMembers.length && managedRtt,
      reasons,
      groupMeta: group,
      coreCapabilities: Object.fromEntries(validCapabilities.map((capability) => [capability.core, capability])),
    };
    if (operation === 'build') {
      result.load = result.debug = false;
    }
    if (operation === 'load') {
      result.build = result.debug = false;
    }
    if (operation === 'debug') {
      result.build = result.load = false;
    }
    if (operation === 'console') {
      result.build = result.load = result.debug = false;
    }
    return result;
  }

  private getCoreCapability(board: string, core: string): CoreCapability | undefined {
    return this.catalog?.devices?.[board]?.cores?.[core];
  }

  public shutdown(): void { this.setupOperationsReady = false; this.closed = true; }
  public dispose(): void {
    this.closed = true; this._onDidChangeSelection.dispose();
  }
}

