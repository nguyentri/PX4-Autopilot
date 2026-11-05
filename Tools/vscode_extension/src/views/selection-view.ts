import * as vscode from 'vscode';
import { SelectionStore } from '../selection-store';
import { WorkspaceTreeItem } from '../tree-item';

export class SelectionViewProvider implements vscode.TreeDataProvider<WorkspaceTreeItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<WorkspaceTreeItem | undefined | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(
    private readonly store: SelectionStore,
    private readonly extensionUri?: vscode.Uri
  ) {
    this.store.onDidChangeSelection(() => this.refresh());
  }

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: WorkspaceTreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(): Thenable<WorkspaceTreeItem[]> {
    const sel = this.store.getSelection();
    const probe = this.store.getSelectedProbe() || 'Automatic / None';
    const target = sel.group || (sel.build.family === 'px4' ? sel.build.target : sel.build.config);
    const targetLabel = sel.group ? `MULTICORE : ${sel.group}` : `${sel.build.family.toUpperCase()} : ${target}`;
    const selectedCore = this.store.getSelectedCore();
    const transport = this.store.getConsoleTransport(selectedCore);

    const logoIcon = this.extensionUri
      ? vscode.Uri.joinPath(this.extensionUri, 'media', 'icon.png')
      : new vscode.ThemeIcon('circuit-board');

    const items = [
      new WorkspaceTreeItem('OneKiwi-Px4-Nuttx', vscode.TreeItemCollapsibleState.None, {
        iconPath: logoIcon,
        command: {
          command: 'vscode.open',
          title: 'Open OneKiwi Website',
          arguments: [vscode.Uri.parse('https://onekiwi.com.vn/')],
        },
        tooltip: new vscode.MarkdownString(
          '**OneKiwi-Px4-Nuttx**\n\n' +
          'OneKiwi unified PX4 Autopilot & NuttX RTOS development environment for Renesas RZ/V2H & RA8 hardware.\n\n' +
          'Website: [https://onekiwi.com.vn/](https://onekiwi.com.vn/)'
        ),
      }),
      new WorkspaceTreeItem('Board', vscode.TreeItemCollapsibleState.None, {
        description: sel.board,
        iconPath: new vscode.ThemeIcon('circuit-board'),
        tooltip: new vscode.MarkdownString(`**Target Board:** \`${sel.board}\`\n\nHardware target platform and peripheral mapping.`),
      }),
      new WorkspaceTreeItem('Core', vscode.TreeItemCollapsibleState.None, {
        description: sel.core === 'multicore' ? `${selectedCore} (selected member)` : selectedCore,
        iconPath: new vscode.ThemeIcon('chip'),
        command: sel.core === 'multicore' ? { command: 'px4Nuttx.selectCore', title: 'Change Group Core' } : undefined,
        tooltip: new vscode.MarkdownString(`**Active Execution Core:** \`${selectedCore}\`\n\n${sel.core === 'multicore' ? 'Click to switch selected member core in this multicore group.' : 'Dedicated single-core profile.'}`),
      }),
      new WorkspaceTreeItem('Target', vscode.TreeItemCollapsibleState.None, {
        description: targetLabel,
        iconPath: new vscode.ThemeIcon('file-binary'),
        command: { command: 'px4Nuttx.selectProfile', title: 'Change Target' },
        tooltip: new vscode.MarkdownString(`**Firmware Target / Profile:** \`${target}\`\n\nFamily: \`${sel.build.family.toUpperCase()}\`\n\nClick to choose another target profile or multicore group.`),
      }),
      new WorkspaceTreeItem('Mode', vscode.TreeItemCollapsibleState.None, {
        description: sel.build.mode,
        iconPath: new vscode.ThemeIcon('settings-gear'),
        tooltip: new vscode.MarkdownString(`**Build Mode:** \`${sel.build.mode}\`\n\nIncremental build configuration.`),
      }),
      new WorkspaceTreeItem('Debug Probe', vscode.TreeItemCollapsibleState.None, {
        description: probe,
        iconPath: new vscode.ThemeIcon('plug'),
        command: { command: 'px4Nuttx.selectProbe', title: 'Change Probe' },
        tooltip: new vscode.MarkdownString(`**Debug Probe:** \`${probe}\`\n\nClick to select or change connected SEGGER J-Link probe.`),
      }),
      new WorkspaceTreeItem('Console Transport', vscode.TreeItemCollapsibleState.None, {
        description: `${transport.toUpperCase()} (manual)`,
        iconPath: new vscode.ThemeIcon('terminal'),
        tooltip: new vscode.MarkdownString(`**Console Transport:** \`${transport.toUpperCase()}\`\n\nOpen the console manually: serial in a serial terminal, RTT through \`nuttx-rtt-bridge.sh\`.`),
      }),
    ];
    return Promise.resolve(items);
  }
}
