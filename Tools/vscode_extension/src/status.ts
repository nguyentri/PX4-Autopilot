import * as vscode from 'vscode';
import { SelectionStore } from './selection-store';
import { FirmwareSelection } from './types';

export class StatusBarManager implements vscode.Disposable {
  private statusBarItem: vscode.StatusBarItem;

  constructor(private readonly store: SelectionStore) {
    this.statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      100
    );
    this.statusBarItem.command = 'px4Nuttx.selectProfile';
    this.update(this.store.getSelection());

    this.store.onDidChangeSelection((sel) => {
      this.update(sel);
    });
  }

  public show(): void {
    this.statusBarItem.show();
  }

  public update(selection: FirmwareSelection): void {
    const targetName =
      selection.build.family === 'px4'
        ? selection.build.target || 'px4'
        : selection.build.config || 'nuttx';

    const shortTarget = targetName.replace(/^renesas_/, '');
    const probe = this.store.getSelectedProbe();
    const probeInfo = probe ? `Probe: ${probe}` : 'No Probe Selected';

    const selectedCore = this.store.getSelectedCore();
    const transport = this.store.getConsoleTransport(selectedCore);
    const consoleManaged = this.store.getCapabilities('console', selectedCore).console;
    const setup = this.store.getActiveSetup();
    this.statusBarItem.command = setup ? 'px4Nuttx.setup.select' : 'px4Nuttx.selectProfile';
    this.statusBarItem.text = `$(circuit-board) ${setup ? `${setup.name} · ${selection.board}` : `${selection.board}:${selectedCore} (${shortTarget})`}`;
    this.statusBarItem.tooltip = new vscode.MarkdownString(
      `**PX4/NuttX Profile:** ${selection.id}\n\n` +
        `- **Board:** ${selection.board}\n` +
        `- **Core:** ${selectedCore}${selection.core === 'multicore' ? ' (group member)' : ''}\n` +
        `- **Target:** ${targetName} (${selection.build.mode})\n` +
        `- **Console:** ${transport.toUpperCase()}${consoleManaged ? '' : ' (manual-only)'}\n` +
        `- **${probeInfo}**\n\n` +
        `Click to select a different target or profile.`
    );
  }

  public dispose(): void {
    this.statusBarItem.dispose();
  }
}
