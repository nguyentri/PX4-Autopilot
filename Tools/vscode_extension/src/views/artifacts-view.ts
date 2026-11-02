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
    private readonly workspaceRoot: string,
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
        tooltip: new vscode.MarkdownString(
          `**Build Receipt:** \`${receipt.receiptId}\`\n\n` +
          `- **Status:** \`${receipt.status}\`\n` +
          `- **Selection:** \`${receipt.selectionId}\`\n` +
          `- **Board / Core:** \`${receipt.board}:${receipt.core}\`\n` +
          `- **Timestamp:** \`${receipt.timestamp}\`\n` +
          `- **Git Revision:** \`${receipt.gitRevision}\` *(dirty: ${receipt.gitDirty})*\n` +
          `- **Compiler:** \`${receipt.compiler || 'unknown'}\``
        ),
      }),
    ];

    for (const art of receipt.artifacts) {
      const fileName = path.basename(art.path);
      const elfPath = path.resolve(this.workspaceRoot, art.path);
      const sizeKb = (art.size / 1024).toFixed(1);
      items.push(
        new WorkspaceTreeItem(fileName, vscode.TreeItemCollapsibleState.None, {
          description: elfPath,
          iconPath: new vscode.ThemeIcon('file-binary'),
          tooltip: new vscode.MarkdownString(
            `**Artifact:** \`${fileName}\`\n\n` +
            `- **Path:** \`${elfPath}\`\n` +
            `- **Size:** \`${sizeKb} KB\` (${art.size} bytes)\n` +
            `- **SHA-256:** \`${art.sha256}\`\n` +
            `- **Target Core:** \`${art.core || 'generic'}\``
          ),
        })
      );
      if (art.entryPoint) {
        items.push(
          new WorkspaceTreeItem('Entry Point', vscode.TreeItemCollapsibleState.None, {
            description: art.entryPoint,
            iconPath: new vscode.ThemeIcon('sign-in'),
            tooltip: new vscode.MarkdownString(`**ELF Entry Point Address:** \`${art.entryPoint}\``),
          })
        );
      }
      if (art.rttAddress) {
        items.push(
          new WorkspaceTreeItem('RTT Control Block', vscode.TreeItemCollapsibleState.None, {
            description: art.rttAddress,
            iconPath: new vscode.ThemeIcon('terminal'),
            tooltip: new vscode.MarkdownString(`**_SEGGER_RTT Control Block Address:** \`${art.rttAddress}\``),
          })
        );
      }
    }

    return Promise.resolve(items);
  }
}

