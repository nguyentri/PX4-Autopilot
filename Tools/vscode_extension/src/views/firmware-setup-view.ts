import * as path from 'path';
import * as vscode from 'vscode';
import { SelectionStore } from '../selection-store';
import { R8Core } from '../types';
import { WorkspaceTreeItem } from '../tree-item';
import { SetupRow, SetupRowFactory, coreLabel } from './firmware-setup-rows';

/**
 * Firmware Setup: collapsible Setup, R8-0, R8-1, Actions and Load history
 * groups. Rows stay in place while a job runs; their actions turn inert.
 */
export class FirmwareSetupViewProvider implements vscode.TreeDataProvider<WorkspaceTreeItem>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<WorkspaceTreeItem | undefined | void>();
  public readonly onDidChangeTreeData = this.changed.event;
  private readonly subscription: vscode.Disposable;
  private readonly rows: SetupRowFactory;

  constructor(private readonly store: SelectionStore) {
    this.subscription = store.onDidChangeSelection(() => this.refresh());
    this.rows = new SetupRowFactory(store);
  }

  public refresh(): void {
    this.changed.fire();
  }

  public getTreeItem(item: WorkspaceTreeItem): vscode.TreeItem {
    return item;
  }

  private row(label: string, description: string, command?: string, core?: R8Core,
    tooltip?: string | vscode.MarkdownString, disabledReason?: string): SetupRow {
    return this.rows.row(label, description, command, core, tooltip, disabledReason);
  }

  public async getChildren(element?: WorkspaceTreeItem): Promise<WorkspaceTreeItem[]> {
    if (element) {
      return (element as SetupRow).children || [];
    }
    return this.rootRows();
  }

  private async rootRows(): Promise<SetupRow[]> {
    if (vscode.workspace.isTrusted === false) {
      return [this.row('Workspace trust required', 'Trust this workspace to prepare, load and debug images.')];
    }

    if (this.store.getStateError()) { return [this.row('Saved state preserved · read-only', this.store.getStateError()!)]; }
    const group = this.store.getGroupMeta();
    if (group?.loadRecipe !== 'rzv-dual-cr8-ram') {
      // The hint opens the Target picker directly, where the Multicore groups live.
      const hint = this.row('Select a dual-CR8 group', 'Click to choose a Multicore group', undefined, undefined,
        'Opens the Target picker. Choose an entry marked (Multicore). RZ/V2H CR8 RAM loading only; RA8P1 and CM33 routes are unavailable.');
      hint.command = { command: 'px4Nuttx.selectProfile', title: 'Choose a Multicore group' };
      return [hint];
    }

    const caps = this.store.getCatalog()?.capabilities;
    if (caps?.importImages !== 1 || !caps.receiptVersions?.includes(2)) {
      return [this.row('Backend update required', 'Update the extension and checkout together, then Refresh.')];
    }

    const state = this.store.getPreparedPair();
    const busy = this.store.getTargetTransition() || (this.store.hasWorkflow() ? 'Firmware workflow in progress'
      : this.store.isPreparingImages() ? 'Preparing images' : '');
    const changes = Object.keys(state?.sourceChanges || {});
    let status = 'Waiting for images';
    if (state?.prepared?.artifacts.length === 2) {
      status = 'Ready';
    }
    if (changes.length) {
      status = 'Source changed';
    }
    if (state?.validationError) {
      status = 'Needs validation';
    }
    if (state?.pending) {
      status = 'Preparation pending';
    }
    if (busy) {
      status = busy;
    }
    const setup = this.store.getActiveSetup();
    const complete = state?.prepared?.artifacts.length === 2 && !state.pending && !state.validationError && !changes.length;
    const busyReason = busy || undefined;
    const setupRows = [
      this.row('Save As', 'Keep another independent image variant', 'saveAs', undefined, undefined, busyReason),
      this.row('Rename', 'Change this setup name', 'rename', undefined, undefined, busyReason),
      this.row('Board', this.store.getSelection().board),
      this.row('Probe', this.store.getSelectedProbe() || 'Select J-Link', 'probe', undefined, undefined, busyReason),
      this.row('Build mode', this.store.getSelection().build.mode || 'incremental', 'mode', undefined, undefined, busyReason),
      this.row('Sessions', this.store.hasOwnedSessions() ? 'Active · use Stop Sessions before switching' : 'Stopped'),
      this.row('Build readiness', 'Fixed group builder · prerequisite details in Readiness'),
      this.row('RAM load readiness', !complete ? 'Prepare and validate both images' : !this.store.getSelectedProbe() ? 'Select J-Link' : state?.history?.message === 'Recover Both required' ? 'Recovery required' : 'Captured pair ready'),
      this.row('Debug readiness', state?.history?.verified ? 'Pair history verified · Cortex-Debug required' : 'Load this exact pair first'),
      this.row('Pair', status, undefined, undefined, state?.validationError || status),
    ];
    const warning = this.store.getStateError() || this.store.getCompatibilityWarning();
    if (warning) { setupRows.push(this.row('State needs attention', warning)); }
    const setupName = setup?.name || group.name || this.store.getSelection().group || 'Unavailable';
    const probe = this.store.getSelectedProbe();
    const items: SetupRow[] = [this.rows.group(
      this.row('Setup', probe ? `${setupName} · probe ${probe}` : setupName, 'select', undefined, undefined, busyReason),
      setupRows, true, 'setupGroup')];

    for (const core of ['cr8_0', 'cr8_1'] as R8Core[]) {
      const label = coreLabel(core);
      const member = group.members.find((value) => value.core === core)!;
      const image = state?.prepared?.artifacts.find((value) => value.core === core);
      const source = state?.sources[core];
      const sourcePath = source && ('path' in source ? source.path : source.receiptPath);
      const notice = state?.sourceChanges?.[core] ? 'Source changed' : state?.acknowledged?.[core] ? 'Original source outdated' : '';
      const coreRows: SetupRow[] = [];
      if (image) {
        coreRows.push(this.row(`${label} ELF`, this.store.resolveReceiptPath(image.path)));
      }
      coreRows.push(this.row(`${label} profile`, member.target || member.config || 'Unavailable'));
      coreRows.push(this.row(`Build ${label}`, 'Build and capture this member only', 'buildCore', core, undefined, busyReason));
      coreRows.push(this.rows.consoleRow(core, image?.path, busyReason));
      if (!busy && state?.sourceChanges?.[core]) {
        coreRows.push(
          this.row(`Keep Captured ${core}`, 'Use captured bytes; retain outdated-source notice', 'keepCaptured', core),
          this.row(`Import Updated ${core}`, 'Capture the current original again', 'importUpdated', core)
        );
      }
      const coreRow = this.row(
        label,
        image ? `${path.basename(image.path)} · ${notice || 'Captured'}` : `Waiting for ${core}`,
        'browse',
        core,
        `${member.target || member.config}\nSource: ${source?.kind || 'none'} ${sourcePath || ''}\nCaptured: ${image?.path || 'none'}\nSHA-256: ${image?.sha256 || 'none'}\nEvidence: ${image?.provenance?.evidence || 'unknown'}\nAddress: ${image?.checks?.address || 'unchecked'}\nHardware qualified: no\n${notice}`,
        busyReason
      );
      // Busy keeps the label and file name readable rather than the reason.
      if (busy) { coreRow.description = image ? `${path.basename(image.path)} · ${busy}` : `Waiting for ${core}`; }
      items.push(this.rows.group(coreRow, coreRows, true, `setupCore.${core === 'cr8_0' ? 'r8_0' : 'r8_1'}`));
    }

    const actions: Array<[string, string, string]> = [
      ['Browse ELF', 'Choose a core and capture an exact image', 'browse'],
      ['Choose Build Folder', 'Choose a core, then an exact ELF inside a folder', 'folder'],
      ['Use Build Receipt', 'Choose an existing matching build explicitly', 'useBuild'],
      ['Build All', 'Build through the existing group builder', 'buildBoth'],
      ['Build & Load', 'Explicitly build, capture, then load this exact pair', 'buildAndLoad'],
      ['Stop Sessions', 'Stop this extension’s debugger session and RTT bridge', 'stopSessions'],
      ['Validate Images', 'Check source changes and captured hashes without hardware', 'validate'],
    ];
    const anyRtt = (['cr8_0', 'cr8_1'] as R8Core[]).some((core) => this.store.getConsoleTransport(core) === 'rtt');
    if (anyRtt) {
      actions.splice(5, 0, ['Build, Load & Trace', 'Build both, load both, then trace in the RTT Monitor', 'buildLoadTrace']);
      actions.push(['Stop RTT Bridge', 'Free the probe before Load, Recover or Debug', 'stopRtt']);
    }

    if (state?.pending) {
      actions.push(['Resume Preparation', 'Resume this exact pending request', 'resume']);
    }

    const pairIsReady = caps.preparedIdentity === 1
      && state?.prepared?.artifacts.length === 2
      && !state.pending
      && !state.validationError
      && !changes.length;
    if (pairIsReady) {
      const recoveryRequired = state.history?.message === 'Recover Both required';
      if (!recoveryRequired) {
        actions.push(['Load Both to RAM', 'Load this captured pair; no implicit build', 'loadBoth']);
      }
      actions.push(['Recover Both', 'Explicit guarded recovery reload of this pair', 'recoverBoth']);
      if (caps.strictLoadedIdentity === 1 && !recoveryRequired) {
        actions.push(
          ['Debug R8-0', 'Require matching verified pair history; one debug session', 'debugR80'],
          ['Debug R8-1', 'Require matching verified pair history; one debug session', 'debugR81']
        );
      }
    }
    const actionRows = actions.map(([label, description, command]) =>
      this.row(label, description, command, undefined, undefined, busyReason));
    items.push(this.rows.group(this.row('Actions', busy || `${actionRows.length} actions`), actionRows, true, 'setupActions'));

    if (state?.history) {
      items.push(this.row(
        'Load history',
        state.history.message,
        undefined,
        undefined,
        `${state.history.message}\n${state.history.timestamp || ''}\nHistorical evidence; no live target polling.`
      ));
    }
    return items;
  }

  public dispose(): void {
    this.subscription.dispose();
    this.changed.dispose();
  }
}
