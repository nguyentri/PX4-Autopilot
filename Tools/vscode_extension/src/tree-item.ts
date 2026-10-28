import * as vscode from 'vscode';

export class WorkspaceTreeItem extends vscode.TreeItem {
  constructor(
    label: string,
    collapsibleState: vscode.TreeItemCollapsibleState = vscode.TreeItemCollapsibleState.None,
    options?: {
      description?: string;
      iconPath?: vscode.ThemeIcon;
      command?: vscode.Command;
      tooltip?: string | vscode.MarkdownString;
    }
  ) {
    super(label, collapsibleState);
    if (options) {
      this.description = options.description;
      this.iconPath = options.iconPath;
      this.command = options.command;
      this.tooltip = options.tooltip;
    }
  }
}
