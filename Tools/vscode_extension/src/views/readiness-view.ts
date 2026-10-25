import * as vscode from 'vscode';
import { BackendClient } from '../backend-client';
import { WorkspaceTreeItem } from '../tree-item';
import { DoctorData } from '../types';

export class ReadinessViewProvider implements vscode.TreeDataProvider<WorkspaceTreeItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<WorkspaceTreeItem | undefined | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
  private doctorData: DoctorData | null = null;

  constructor(private readonly client: BackendClient) {}

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  async setDoctorData(data: DoctorData): Promise<void> {
    this.doctorData = data;
    this.refresh();
  }

  getTreeItem(element: WorkspaceTreeItem): vscode.TreeItem {
    return element;
  }

  async getChildren(): Promise<WorkspaceTreeItem[]> {
    if (vscode.workspace?.isTrusted === false) {
      return [
        new WorkspaceTreeItem('Workspace Trust Required', vscode.TreeItemCollapsibleState.None, {
          description: 'Trust this folder to run prerequisite checks',
          iconPath: new vscode.ThemeIcon('lock'),
          command: { command: 'workbench.action.manageTrust', title: 'Manage Workspace Trust' },
        }),
      ];
    }
    if (!this.doctorData) {
      try {
        const res = await this.client.runDoctor();
        if (res.data?.tools) {
          this.doctorData = res.data;
        }
      } catch (e) {
        return [
          new WorkspaceTreeItem('Run Doctor Check', vscode.TreeItemCollapsibleState.None, {
            description: 'Click to evaluate prerequisites',
            iconPath: new vscode.ThemeIcon('refresh'),
            command: { command: 'px4Nuttx.checkDoctor', title: 'Check Prerequisites' },
          }),
        ];
      }
    }

    if (!this.doctorData) {
      return [];
    }

    const items: WorkspaceTreeItem[] = [];
    if (this.doctorData.readiness) {
      for (const [operation, ready] of Object.entries(this.doctorData.readiness)) {
        items.push(
          new WorkspaceTreeItem(`${operation[0].toUpperCase()}${operation.slice(1)} readiness`, vscode.TreeItemCollapsibleState.None, {
            description: ready ? 'Ready' : 'Blocked by host/probe prerequisites',
            iconPath: new vscode.ThemeIcon(ready ? 'check' : 'warning'),
            tooltip: ready
              ? `${operation} prerequisites are available.`
              : `The ${operation} operation is currently blocked; inspect the tool rows below for remediation.`,
          })
        );
      }
    }
    for (const [toolName, info] of Object.entries(this.doctorData.tools)) {
      const ok = info.ok;
      items.push(
        new WorkspaceTreeItem(toolName, vscode.TreeItemCollapsibleState.None, {
          description: ok ? 'Available' : `Missing / Incompatible${info.remediation ? ` · ${info.remediation}` : ''}`,
          iconPath: new vscode.ThemeIcon(
            ok ? 'check' : 'error',
            ok ? new vscode.ThemeColor('testing.iconPassed') : new vscode.ThemeColor('testing.iconFailed')
          ),
          tooltip: [info.info, info.path, info.remediation].filter(Boolean).join('\n') || '',
        })
      );
    }
    const subOk = this.doctorData.submodules?.nuttxInitialized;
    items.push(
      new WorkspaceTreeItem('NuttX Submodule', vscode.TreeItemCollapsibleState.None, {
        description: subOk ? 'Initialized' : 'Uninitialized',
        iconPath: new vscode.ThemeIcon(subOk ? 'check' : 'warning'),
      })
    );
    const probeCount = this.doctorData.probes?.length || 0;
    items.push(
      new WorkspaceTreeItem('J-Link Probes', vscode.TreeItemCollapsibleState.None, {
        description: probeCount > 0 ? `${probeCount} connected` : 'None connected; build-only actions may still run',
        iconPath: new vscode.ThemeIcon(probeCount > 0 ? 'check' : 'info'),
      })
    );

    return items;
  }
}
