import * as vscode from 'vscode';
import { SelectionStore } from '../selection-store';
import { R8Core } from '../types';
import { WorkspaceTreeItem } from '../tree-item';

/** A Firmware Setup row; group rows carry their children. */
export type SetupRow = WorkspaceTreeItem & { core?: R8Core; setupId?: string; children?: SetupRow[] };

export const coreLabel = (core: R8Core): string => (core === 'cr8_0' ? 'R8-0' : 'R8-1');

const FIXED_ICONS: Record<string, string> = {
  Setup: 'layers', 'Save As': 'save-as', Rename: 'edit', Board: 'circuit-board', Probe: 'plug',
  'Build mode': 'settings-gear', Sessions: 'pulse', 'Build readiness': 'tools', 'RAM load readiness': 'cloud-upload',
  'Debug readiness': 'debug-alt', 'Serial device': 'plug', 'Load history': 'history', 'Browse ELF': 'file-binary',
  'Choose Build Folder': 'folder', 'Use Build Receipt': 'tag', 'Build All': 'play', 'Build & Load': 'rocket',
  'Build, Load & Trace': 'rocket', 'Stop Sessions': 'stop-circle', 'Stop RTT Bridge': 'debug-disconnect',
  'Validate Images': 'checklist', 'Resume Preparation': 'debug-continue', 'Load Both to RAM': 'cloud-upload',
  'Debug R8-0': 'debug-alt', 'Debug R8-1': 'debug-alt', 'Workspace trust required': 'lock',
  'Select a dual-CR8 group': 'target', Actions: 'tools', 'Open RTT Monitor': 'terminal',
};

/** Builds the rows of the Firmware Setup view; the view only arranges them. */
export class SetupRowFactory {
  constructor(private readonly store: SelectionStore) {}

  private themeColor(id: string): vscode.ThemeColor | undefined {
    return typeof vscode.ThemeColor === 'function' ? new vscode.ThemeColor(id) : undefined;
  }

  private warningIcon(): vscode.ThemeIcon {
    return new vscode.ThemeIcon('warning', this.themeColor('problemsWarningIcon.foreground'));
  }

  public icon(label: string, command?: string, status?: string): vscode.ThemeIcon {
    if (label.endsWith(' ELF')) { return new vscode.ThemeIcon('file-binary'); }
    if (label.startsWith('Build R8-')) { return new vscode.ThemeIcon('play'); }
    if (label.startsWith('Console R8-') || label.startsWith('Trace R8-')) { return new vscode.ThemeIcon('terminal'); }
    if (label.startsWith('Keep Captured')) { return new vscode.ThemeIcon('check'); }
    if (label.startsWith('Import Updated')) { return new vscode.ThemeIcon('refresh'); }
    if (label === 'R8-0' || label === 'R8-1') { return new vscode.ThemeIcon('chip'); }
    if (label === 'R8-0 profile' || label === 'R8-1 profile') { return new vscode.ThemeIcon('symbol-misc'); }
    if (label === 'Recover Both' || label === 'State needs attention' || label === 'Backend update required') {
      return this.warningIcon();
    }
    if (label === 'Pair') {
      if (this.store.getTargetTransition() || this.store.hasWorkflow() || this.store.isPreparingImages()) {
        return new vscode.ThemeIcon('sync~spin');
      }
      if (status === 'Ready') { return new vscode.ThemeIcon('pass-filled', this.themeColor('testing.iconPassed')); }
      if (status === 'Preparation pending') {
        return new vscode.ThemeIcon('debug-pause', this.themeColor('problemsWarningIcon.foreground'));
      }
      if (status?.includes('validation') || status?.includes('warning') || status?.includes('Recovery') || status?.includes('changed')) {
        return this.warningIcon();
      }
      return new vscode.ThemeIcon('symbol-property');
    }
    return new vscode.ThemeIcon(FIXED_ICONS[label] || (command ? 'tools' : 'info'));
  }

  /**
   * One row. `disabledReason` keeps an action visible but inert while a job
   * runs, so the layout does not jump.
   */
  public row(label: string, description: string, command?: string, core?: R8Core,
    tooltip?: string | vscode.MarkdownString, disabledReason?: string): SetupRow {
    const setupId = this.store.getActiveSetup()?.id;
    const token = this.store.captureSetupToken(core, true);
    const enabled = command && !disabledReason && this.store.isSetupOperationsReady();
    const item = new WorkspaceTreeItem(label, vscode.TreeItemCollapsibleState.None, {
      description: disabledReason ? `Unavailable · ${disabledReason}` : description,
      tooltip: tooltip || description,
      iconPath: this.icon(label, command, description),
      command: enabled ? {
        command: `px4Nuttx.setup.${command}`, title: label, arguments: [{ setupId, core, token }],
      } : undefined,
    }) as SetupRow;
    item.id = `setup:${setupId || ''}:${core || ''}:${command || label}`;
    item.contextValue = core ? 'dualCoreImage' : 'dualCoreAction';
    Object.assign(item, { core, setupId, token });
    return item;
  }

  /** Turns a row into a group node; rows inside keep their own commands. */
  public group(item: SetupRow, children: SetupRow[], expanded: boolean, contextValue?: string): SetupRow {
    item.collapsibleState = expanded ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.Collapsed;
    item.children = children;
    if (contextValue) { item.contextValue = contextValue; }
    return item;
  }

  /**
   * The extension never opens a terminal for a UART console. An RTT row
   * starts the backend-owned bridge and opens the RTT Monitor on it.
   */
  public consoleRow(core: R8Core, elf: string | undefined, disabledReason?: string): SetupRow {
    const transport = this.store.getConsoleTransport(core);
    const label = `Console ${coreLabel(core)}`;
    if (transport.startsWith('sci')) {
      const uart = transport.toUpperCase();
      return this.row(label, `Manual · ${uart} 115200 8N1`, undefined, undefined,
        `Open the board ${uart} UART in your own serial terminal (115200 8N1).`);
    }
    if (transport === 'rtt') {
      return this.row(label, 'RTT · Trace in the RTT Monitor', 'startRtt', core,
        'Starts the RTT bridge for this core after a verified Load Both and shows it in the RTT Monitor. ' +
        'Load, Recover and Debug pause the bridge and resume it afterwards.\n' +
        `Manual alternative: platforms/nuttx/Debug/nuttx-rtt-bridge.sh start ${core} ${elf || '<elf>'}`,
        disabledReason);
    }
    return this.row(label, `Manual · ${transport.toUpperCase()}`);
  }
}
