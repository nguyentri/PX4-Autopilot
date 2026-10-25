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
} from './types';

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

interface ReceiptBinding {
  path: string;
  receiptId?: string;
}

interface PersistedFolderState {
  selection?: FirmwareSelection;
  selectedProbeSerial?: string;
  selectedCore?: string;
  receipts?: Record<string, ReceiptBinding>;
}

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

  private activeSelection: FirmwareSelection;
  private selectedProbeSerial = '';
  private selectedCore = '';
  private receiptBindings: Record<string, ReceiptBinding> = {};
  private catalog: CatalogData | null = null;

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly workspaceRoot: string
  ) {
    const saved = this.loadPersistedState();
    this.activeSelection = this.loadInitialSelection(saved);
    this.selectedProbeSerial = saved.selectedProbeSerial || '';
    this.selectedCore = saved.selectedCore || '';
    this.receiptBindings = saved.receipts || {};
  }

  public getWorkspaceRoot(): string {
    return this.workspaceRoot;
  }

  private stateKey(): string {
    return `${SELECTION_STATE_KEY}.${this.workspaceRoot}`;
  }

  private loadPersistedState(): PersistedFolderState {
    const saved = this.context.workspaceState.get<PersistedFolderState>(this.stateKey());
    return saved ? clone(saved) : {};
  }

  private persistState(): Thenable<void> {
    return this.context.workspaceState.update(this.stateKey(), {
      selection: this.activeSelection,
      selectedProbeSerial: this.selectedProbeSerial,
      selectedCore: this.selectedCore,
      receipts: this.receiptBindings,
    } satisfies PersistedFolderState);
  }

  private loadInitialSelection(saved: PersistedFolderState): FirmwareSelection {
    const customConfig = path.join(this.workspaceRoot, '.vscode', 'firmware-workspace.json');
    if (fs.existsSync(customConfig)) {
      try {
        const parsed = JSON.parse(fs.readFileSync(customConfig, 'utf-8')) as FirmwareSelection;
        if (parsed && parsed.schemaVersion === 1) {
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
    const members = this.getGroupMembers();
    if (this.activeSelection.core !== 'multicore' || !members.some((member) => member.core === core)) {
      throw new Error(`Core ${core} is not a member of the selected firmware group.`);
    }
    this.selectedCore = core;
    await this.persistState();
    this._onDidChangeSelection.fire(this.getSelection());
  }

  public async setSelection(selection: FirmwareSelection): Promise<void> {
    this.activeSelection = clone(selection);
    if (selection.core !== 'multicore') {
      this.selectedCore = selection.core;
    } else if (!this.getGroupMembers().some((member) => member.core === this.selectedCore)) {
      this.selectedCore = '';
    }
    this.refreshReceipts();
    await this.persistState();
    if (trusted()) {
      this.ensureSelectionFileOnDisk();
    }
    this._onDidChangeSelection.fire(this.getSelection());
  }

  public async setSelectedProbe(serial: string): Promise<void> {
    this.selectedProbeSerial = serial.trim();
    await this.persistState();
    this._onDidChangeSelection.fire(this.getSelection());
  }

  public getSelectionFilePath(): string {
    return path.join(this.workspaceRoot, '.vscode', 'active-selection.json');
  }

  /** Write only at an explicit, trusted operation boundary. */
  public ensureSelectionFileOnDisk(): string {
    const file = this.getSelectionFilePath();
    if (!trusted()) {
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
    if (!trusted()) {
      throw new Error('Workspace trust is required before writing a selection snapshot.');
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
    const binding = this.receiptBindings[selectionKey(selection)];
    if (!binding || !this.receiptMatchesSelection(binding.path, selection)) {
      return null;
    }
    return binding.path;
  }

  public setReceiptPath(receiptPath: string | null, selection: FirmwareSelection = this.activeSelection): void {
    const key = selectionKey(selection);
    if (!receiptPath) {
      delete this.receiptBindings[key];
    } else {
      const receipt = this.readReceipt(receiptPath);
      if (!receipt || receipt.selectionId !== selection.id || receipt.status !== 'committed') {
        return;
      }
      this.receiptBindings[key] = {
        path: receiptPath,
        receiptId: receipt.receiptId,
      };
    }
    void this.persistState();
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
  public refreshReceipts(): void {
    if (!trusted()) {
      return;
    }
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
      this.setReceiptPath(path.relative(this.workspaceRoot, candidates[0].file));
    }
  }

  private receiptMatchesSelection(receiptPath: string, selection: FirmwareSelection): boolean {
    const receipt = this.readReceipt(receiptPath);
    if (!receipt || receipt.schemaVersion !== 1 || receipt.status !== 'committed' || receipt.selectionId !== selection.id
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
    this.refreshReceipts();
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

  public dispose(): void {
    this._onDidChangeSelection.dispose();
  }
}

