import * as path from 'path';
import * as vscode from 'vscode';
import { SelectionStore } from '../selection-store';
import { R8Core } from '../types';
import { WorkspaceTreeItem } from '../tree-item';

export class FirmwareSetupViewProvider implements vscode.TreeDataProvider<WorkspaceTreeItem>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<WorkspaceTreeItem | undefined | void>();
  public readonly onDidChangeTreeData = this.changed.event;
  private readonly subscription: vscode.Disposable;

  constructor(private readonly store: SelectionStore) {
    this.subscription = store.onDidChangeSelection(() => this.refresh());
  }

  public refresh(): void {
    this.changed.fire();
  }

  public getTreeItem(item: WorkspaceTreeItem): vscode.TreeItem {
    return item;
  }

  private themeColor(id: string): vscode.ThemeColor | undefined {
    return typeof vscode.ThemeColor === 'function' ? new vscode.ThemeColor(id) : undefined;
  }

  private getSemanticIcon(label: string, command?: string, status?: string): vscode.ThemeIcon {
    if (label.startsWith('Build R8-')) {
      return new vscode.ThemeIcon('play');
    }
    if (label.startsWith('Console R8-')) {
      return new vscode.ThemeIcon('terminal');
    }
    if (label.startsWith('Keep Captured')) {
      return new vscode.ThemeIcon('check');
    }
    if (label.startsWith('Import Updated')) {
      return new vscode.ThemeIcon('refresh');
    }
    if (label === 'R8-0' || label === 'R8-1') {
      return new vscode.ThemeIcon('chip');
    }
    if (label === 'R8-0 profile' || label === 'R8-1 profile') {
      return new vscode.ThemeIcon('symbol-misc');
    }
    switch (label) {
      case 'Setup':
        return new vscode.ThemeIcon('layers');
      case 'Save As':
        return new vscode.ThemeIcon('save-as');
      case 'Rename':
        return new vscode.ThemeIcon('edit');
      case 'Board':
        return new vscode.ThemeIcon('circuit-board');
      case 'Probe':
        return new vscode.ThemeIcon('plug');
      case 'Build mode':
        return new vscode.ThemeIcon('settings-gear');
      case 'Sessions':
        return new vscode.ThemeIcon('pulse');
      case 'Build readiness':
        return new vscode.ThemeIcon('tools');
      case 'RAM load readiness':
        return new vscode.ThemeIcon('cloud-upload');
      case 'Debug readiness':
        return new vscode.ThemeIcon('debug-alt');
      case 'Pair': {
        if (this.store.getTargetTransition() || this.store.hasWorkflow() || this.store.isPreparingImages()) {
          return new vscode.ThemeIcon('sync~spin');
        }
        if (status === 'Ready') {
          return new vscode.ThemeIcon('pass-filled', this.themeColor('testing.iconPassed'));
        }
        if (status === 'Preparation pending') {
          return new vscode.ThemeIcon('debug-pause', this.themeColor('problemsWarningIcon.foreground'));
        }
        if (status?.includes('validation') || status?.includes('warning') || status?.includes('Recovery') || status?.includes('changed')) {
          return new vscode.ThemeIcon('warning', this.themeColor('problemsWarningIcon.foreground'));
        }
        return new vscode.ThemeIcon('symbol-property');
      }
      case 'State needs attention':
        return new vscode.ThemeIcon('warning', this.themeColor('problemsWarningIcon.foreground'));
      case 'Serial device':
        return new vscode.ThemeIcon('plug');
      case 'Load history':
        return new vscode.ThemeIcon('history');
      case 'Browse ELF':
        return new vscode.ThemeIcon('file-binary');
      case 'Choose Build Folder':
        return new vscode.ThemeIcon('folder');
      case 'Use Build Receipt':
        return new vscode.ThemeIcon('tag');
      case 'Build All':
        return new vscode.ThemeIcon('play');
      case 'Build & Load':
        return new vscode.ThemeIcon('rocket');
      case 'Stop Sessions':
        return new vscode.ThemeIcon('stop-circle');
      case 'Validate Images':
        return new vscode.ThemeIcon('checklist');
      case 'Resume Preparation':
        return new vscode.ThemeIcon('debug-continue');
      case 'Load Both to RAM':
        return new vscode.ThemeIcon('cloud-upload');
      case 'Recover Both':
        return new vscode.ThemeIcon('warning', this.themeColor('problemsWarningIcon.foreground'));
      case 'Debug R8-0':
      case 'Debug R8-1':
        return new vscode.ThemeIcon('debug-alt');
      case 'Workspace trust required':
        return new vscode.ThemeIcon('lock');
      case 'Select a dual-CR8 group':
        return new vscode.ThemeIcon('target');
      case 'Backend update required':
        return new vscode.ThemeIcon('warning', this.themeColor('problemsWarningIcon.foreground'));
      default:
        return new vscode.ThemeIcon(command ? 'tools' : 'info');
    }
  }

  private row(
    label: string,
    description: string,
    command?: string,
    core?: R8Core,
    tooltip?: string | vscode.MarkdownString
  ): WorkspaceTreeItem {
    const item = new WorkspaceTreeItem(label, vscode.TreeItemCollapsibleState.None, {
      description,
      tooltip: tooltip || description,
      iconPath: this.getSemanticIcon(label, command, description),
      command: command && this.store.isSetupOperationsReady() ? {
        command: `px4Nuttx.setup.${command}`,
        title: label,
        arguments: [{ setupId: this.store.getActiveSetup()?.id, core, token: this.store.captureSetupToken(core, true) }],
      } : undefined,
    });
    item.id = `setup:${this.store.getActiveSetup()?.id || ''}:${core || ''}:${command || label}`;
    item.contextValue = core ? 'dualCoreImage' : 'dualCoreAction';
    Object.assign(item, { core, setupId: this.store.getActiveSetup()?.id, token: this.store.captureSetupToken(core, true) });
    return item;
  }

  /**
   * Consoles are opened manually outside the extension; this read-only row
   * only names the transport and the command that reaches it.
   */
  private manualConsoleRow(core: R8Core, elf?: string): WorkspaceTreeItem {
    const transport = this.store.getConsoleTransport(core);
    const label = `Console ${core === 'cr8_0' ? 'R8-0' : 'R8-1'}`;
    if (transport.startsWith('sci')) {
      const uart = transport.toUpperCase();
      return this.row(label, `Manual · ${uart} 115200 8N1`, undefined, undefined,
        `Open the board ${uart} UART in your own serial terminal (115200 8N1).`);
    }
    if (transport === 'rtt') {
      return this.row(label, 'Manual · RTT 127.0.0.1:19021', undefined, undefined,
        `platforms/nuttx/Debug/nuttx-rtt-bridge.sh start ${core} ${elf || '<elf>'}\n` +
        'Then connect a terminal (for example μScope) to 127.0.0.1:19021. ' +
        'Stop the bridge before loading or debugging: nuttx-rtt-bridge.sh stop');
    }
    return this.row(label, `Manual · ${transport.toUpperCase()}`);
  }

  public async getChildren(): Promise<WorkspaceTreeItem[]> {
    if (vscode.workspace.isTrusted === false) {
      return [this.row('Workspace trust required', 'Trust this workspace to prepare, load and debug images.')];
    }

    if (this.store.getStateError()) { return [this.row('Saved state preserved · read-only', this.store.getStateError()!)]; }
    const group = this.store.getGroupMeta();
    if (group?.loadRecipe !== 'rzv-dual-cr8-ram') {
      return [this.row('Select a dual-CR8 group', 'Use Select Target/Profile. RZ/V2H CR8 RAM loading only; RA8P1 and CM33 routes are unavailable.')];
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
    const items = [
      this.row('Setup', setup?.name || group.name || this.store.getSelection().group || 'Unavailable', 'select'),
      this.row('Save As', 'Keep another independent image variant', 'saveAs'),
      this.row('Rename', 'Change this setup name', 'rename'),
      this.row('Board', this.store.getSelection().board),
      this.row('Probe', this.store.getSelectedProbe() || 'Select J-Link', 'probe'),
      this.row('Build mode', this.store.getSelection().build.mode || 'incremental', 'mode'),
      this.row('Sessions', this.store.hasOwnedSessions() ? 'Active · use Stop Sessions before switching' : 'Stopped'),
      this.row('Build readiness', 'Fixed group builder · prerequisite details in Readiness'),
      this.row('RAM load readiness', !complete ? 'Prepare and validate both images' : !this.store.getSelectedProbe() ? 'Select J-Link' : state?.history?.message === 'Recover Both required' ? 'Recovery required' : 'Captured pair ready'),
      this.row('Debug readiness', state?.history?.verified ? 'Pair history verified · Cortex-Debug required' : 'Load this exact pair first'),
      this.row('Pair', status, undefined, undefined, state?.validationError || status),
    ];
    const warning = this.store.getStateError() || this.store.getCompatibilityWarning();
    if (warning) { items.push(this.row('State needs attention', warning)); }


    for (const core of ['cr8_0', 'cr8_1'] as R8Core[]) {
      const member = group.members.find((value) => value.core === core)!;
      const image = state?.prepared?.artifacts.find((value) => value.core === core);
      const source = state?.sources[core];
      const sourcePath = source && ('path' in source ? source.path : source.receiptPath);
      const notice = state?.sourceChanges?.[core] ? 'Source changed' : state?.acknowledged?.[core] ? 'Original source outdated' : '';

      items.push(this.row(
        core === 'cr8_0' ? 'R8-0' : 'R8-1',
        image ? `${path.basename(sourcePath || image.path)} · ${notice || 'Captured'}` : `Waiting for ${core}`,
        busy ? undefined : 'browse',
        core,
        `${member.target || member.config}\nSource: ${source?.kind || 'none'} ${sourcePath || ''}\nCaptured: ${image?.path || 'none'}\nSHA-256: ${image?.sha256 || 'none'}\nEvidence: ${image?.provenance?.evidence || 'unknown'}\nAddress: ${image?.checks?.address || 'unchecked'}\nHardware qualified: no\n${notice}`
      ));

      items.push(this.row(`${core === 'cr8_0' ? 'R8-0' : 'R8-1'} profile`, member.target || member.config || 'Unavailable'));
      if (!busy) {
        items.push(this.row(`Build ${core === 'cr8_0' ? 'R8-0' : 'R8-1'}`, 'Build and capture this member only', 'buildCore', core));
        items.push(this.manualConsoleRow(core, image?.path));
      }

      if (!busy && state?.sourceChanges?.[core]) {
        items.push(
          this.row(`Keep Captured ${core}`, 'Use captured bytes; retain outdated-source notice', 'keepCaptured', core),
          this.row(`Import Updated ${core}`, 'Capture the current original again', 'importUpdated', core)
        );
      }
    }

    if (state?.history) {
      items.push(this.row(
        'Load history',
        state.history.message,
        undefined,
        undefined,
        `${state.history.message}\n${state.history.timestamp || ''}\nHistorical evidence; no live target polling.`
      ));
    }

    if (busy) {
      return items;
    }

    const actions: Array<[string, string, string]> = [
      ['Browse ELF', 'Choose a core and capture an exact image', 'browse'],
      ['Choose Build Folder', 'Choose a core, then an exact ELF inside a folder', 'folder'],
      ['Use Build Receipt', 'Choose an existing matching build explicitly', 'useBuild'],
      ['Build All', 'Build through the existing group builder', 'buildBoth'],
      ['Build & Load', 'Explicitly build, capture, then load this exact pair', 'buildAndLoad'],
      ['Stop Sessions', 'Stop only this extension’s debugger session', 'stopSessions'],
      ['Validate Images', 'Check source changes and captured hashes without hardware', 'validate'],
    ];

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

    return items.concat(actions.map(([label, description, command]) => this.row(label, description, command)));
  }

  public dispose(): void {
    this.subscription.dispose();
    this.changed.dispose();
  }
}
