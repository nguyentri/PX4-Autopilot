import * as vscode from 'vscode';

/**
 * True unless VS Code reports the workspace as untrusted. Same rule as the
 * sibling extension: an API without the trust flag counts as trusted.
 */
export function workspaceIsTrusted(): boolean {
  return vscode.workspace?.isTrusted !== false;
}
