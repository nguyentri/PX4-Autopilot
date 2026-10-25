import * as vscode from 'vscode';
import { SelectionStore } from '../selection-store';
import { WorkspaceTreeItem } from '../tree-item';

export class OperationsViewProvider implements vscode.TreeDataProvider<WorkspaceTreeItem> {
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<WorkspaceTreeItem | undefined | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(private readonly store?: SelectionStore) {
    this.store?.onDidChangeSelection(() => this.refresh());
  }

  public refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: WorkspaceTreeItem): vscode.TreeItem {
    return element;
  }

  private action(
    label: string,
    description: string,
    icon: string,
    command: string,
    available: boolean,
    reason: string
  ): WorkspaceTreeItem {
    return new WorkspaceTreeItem(label, vscode.TreeItemCollapsibleState.None, {
      description: available ? description : `Unavailable: ${reason}`,
      iconPath: new vscode.ThemeIcon(available ? icon : 'lock'),
      command: available ? { command, title: label } : undefined,
      tooltip: available ? description : reason,
    });
  }

  getChildren(): Thenable<WorkspaceTreeItem[]> {
    if (vscode.workspace?.isTrusted === false) {
      return Promise.resolve([
        new WorkspaceTreeItem('Workspace Trust Required', vscode.TreeItemCollapsibleState.None, {
          description: 'Trust this folder to execute firmware operations',
          iconPath: new vscode.ThemeIcon('lock'),
          command: { command: 'workbench.action.manageTrust', title: 'Manage Workspace Trust' },
        }),
      ]);
    }

    if (!this.store) {
      return Promise.resolve([
        this.action('Build Target', 'Incremental compile', 'play', 'px4Nuttx.build', true, ''),
        this.action('Clean Rebuild', 'Distclean and compile', 'trash', 'px4Nuttx.cleanRebuild', true, ''),
        this.action('Guarded Load (RAM)', 'Load selected ELF to RAM', 'arrow-up', 'px4Nuttx.load', true, ''),
        this.action('Attach Debugger', 'Cortex-Debug (no reset)', 'debug-alt', 'px4Nuttx.attach', true, ''),
        this.action('Load and Debug', 'Load then attach after verified success', 'debug-restart', 'px4Nuttx.loadAndDebug', true, ''),
        this.action('Start Console', 'Selected core transport', 'terminal', 'px4Nuttx.startConsole', true, ''),
        this.action('Stop Console', 'Stop the owned console bridge', 'primitive-square', 'px4Nuttx.stopConsole', true, ''),
      ]);
    }

    const capabilities = this.store.getCapabilities();
    const reasons = capabilities.reasons.join(' ') || 'Refresh the catalog and select a supported profile.';
    const transport = this.store.getConsoleTransport();
    return Promise.resolve([
      this.action('Build Target', 'Incremental compile', 'play', 'px4Nuttx.build', capabilities.build, reasons),
      this.action('Clean Rebuild', 'Distclean and compile', 'trash', 'px4Nuttx.cleanRebuild', capabilities.build, reasons),
      this.action('Load Selected ELF', 'Load selected ELF to RAM', 'arrow-up', 'px4Nuttx.load', capabilities.load, reasons),
      this.action('Attach Debugger', 'Cortex-Debug (no reset)', 'debug-alt', 'px4Nuttx.attach', capabilities.debug, reasons),
      this.action('Load and Debug', 'Load then attach after verified success', 'debug-restart', 'px4Nuttx.loadAndDebug', capabilities.load && capabilities.debug, reasons),
      this.action(
        `Start Console (${transport.toUpperCase()})`,
        `Selected core: ${this.store.getSelectedCore()}`,
        'terminal',
        'px4Nuttx.startConsole',
        capabilities.console,
        transport === 'none'
          ? 'No supported console transport for the selected core.'
          : transport !== 'rtt'
            ? `${transport.toUpperCase()} is manual-only; use nsh_console_exec.py with the selected serial.`
            : reasons
      ),
      this.action('Stop Console', 'Stop the owned console bridge', 'primitive-square', 'px4Nuttx.stopConsole', true, ''),
    ]);
  }
}

