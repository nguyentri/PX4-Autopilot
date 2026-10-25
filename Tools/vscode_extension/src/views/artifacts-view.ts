import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { SelectionStore } from '../selection-store';
import { ArtifactReceipt } from '../types';
import { WorkspaceTreeItem } from '../tree-item';

export class ArtifactsViewProvider implements vscode.TreeDataProvider<WorkspaceTreeItem> {
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<WorkspaceTreeItem | undefined | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
  private selectedReceipt: ArtifactReceipt | null = null;

  constructor(
    _workspaceRoot: string,
    private readonly store?: SelectionStore
  ) {
    this.store?.onDidChangeSelection(() => this.refresh());
    this.loadSelectedReceipt();
  }

  public refresh(): void {
    this.loadSelectedReceipt();
    this._onDidChangeTreeData.fire();
  }

  public setReceipt(receipt: ArtifactReceipt): void {
    if (this.store) {
      const boundPath = this.store.getReceiptPath();
      const boundReceipt = boundPath ? this.store.readReceipt(boundPath) : null;
      if (!boundReceipt || boundReceipt.receiptId !== receipt.receiptId) {
        return;
      }
    } else {
      return;
    }
    this.selectedReceipt = receipt;
    this._onDidChangeTreeData.fire();
  }

  public getReceipt(): ArtifactReceipt | null {
    return this.selectedReceipt;
  }

  private loadSelectedReceipt(): void {
    this.selectedReceipt = null;
    const receiptPath = this.store?.getReceiptPath();
    if (!receiptPath) {
      return;
    }
    const absolute = this.store?.resolveReceiptPath(receiptPath) || receiptPath;
    try {
      const receipt = JSON.parse(fs.readFileSync(absolute, 'utf-8')) as ArtifactReceipt;
      if (receipt.status === 'committed') {
        this.selectedReceipt = receipt;
      }
    } catch {
      // A deleted/replaced receipt is intentionally rendered as unavailable.
    }
  }

  getTreeItem(element: WorkspaceTreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(): Thenable<WorkspaceTreeItem[]> {
    if (!this.selectedReceipt) {
      const selection = this.store?.getSelection();
      const target = selection?.id || 'the selected profile';
      return Promise.resolve([
        new WorkspaceTreeItem('No Matching Build Receipt', vscode.TreeItemCollapsibleState.None, {
          description: `Build ${target} to create a committed artifact`,
          iconPath: new vscode.ThemeIcon('info'),
          command: { command: 'px4Nuttx.build', title: 'Build Active Target' },
        }),
      ]);
    }

    const receipt = this.selectedReceipt;
    const items: WorkspaceTreeItem[] = [
      new WorkspaceTreeItem(`Receipt: ${receipt.receiptId}`, vscode.TreeItemCollapsibleState.None, {
        description: `${receipt.status} · ${receipt.board}:${receipt.core}`,
        iconPath: new vscode.ThemeIcon('tag'),
        tooltip: `Selection: ${receipt.selectionId}\nTimestamp: ${receipt.timestamp}\nGit: ${receipt.gitRevision} (dirty: ${receipt.gitDirty})`,
      }),
    ];

    for (const art of receipt.artifacts) {
      const fileName = path.basename(art.path);
      const sizeKb = (art.size / 1024).toFixed(1);
      items.push(
        new WorkspaceTreeItem(fileName, vscode.TreeItemCollapsibleState.None, {
          description: `${sizeKb} KB (${art.core || 'generic'})`,
          iconPath: new vscode.ThemeIcon('file-binary'),
          tooltip: `Path: ${art.path}\nSHA-256: ${art.sha256}`,
        })
      );
      if (art.entryPoint) {
        items.push(
          new WorkspaceTreeItem('Entry Point', vscode.TreeItemCollapsibleState.None, {
            description: art.entryPoint,
            iconPath: new vscode.ThemeIcon('sign-in'),
          })
        );
      }
      if (art.rttAddress) {
        items.push(
          new WorkspaceTreeItem('RTT Control Block', vscode.TreeItemCollapsibleState.None, {
            description: art.rttAddress,
            iconPath: new vscode.ThemeIcon('terminal'),
          })
        );
      }
    }

    return Promise.resolve(items);
  }
}

