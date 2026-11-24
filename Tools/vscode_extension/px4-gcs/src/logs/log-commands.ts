// VS Code plumbing for onboard logs: the save dialog, the free-space reading,
// the finish notice with Open and Reveal, and the `Download Log` palette
// command (QuickPick over the vehicle's list, progress notification with
// cancel). The flow itself lives in log-download-service.ts.
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { LogEntryView, LogTransferView, NO_LOGS_TEXT } from '../dashboard/dashboard-messages';
import { LogDownloadHost, LogDownloadService } from './log-download-service';
import { LogListStore } from './log-list-store';
import { formatBytes, logDate, transferText } from './log-transfer-format';

function defaultName(entry: LogEntryView): string {
  const stamp = entry.timeUtc ? new Date(entry.timeUtc * 1000).toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z') : 'nodate';
  return `log-${entry.id}-${stamp}.ulg`;
}

export function createLogHost(defaultFolder: () => string): LogDownloadHost {
  return {
    async pickDestination(entry) {
      const uri = await vscode.window.showSaveDialog({
        title: `Save onboard log ${entry.id} (${formatBytes(entry.size)})`,
        defaultUri: vscode.Uri.file(path.join(defaultFolder(), defaultName(entry))),
        filters: { 'PX4 ULog': ['ulg'], 'All files': ['*'] },
      });
      return uri?.scheme === 'file' ? uri.fsPath : undefined;
    },
    async freeBytes(folder) {
      try {
        const stats = await fs.promises.statfs(folder);
        return stats.bavail * stats.bsize;
      } catch {
        return undefined;
      }
    },
    finished(transfer: LogTransferView) {
      if (transfer.state === 'done' && transfer.path) {
        const file = vscode.Uri.file(transfer.path);
        void vscode.window.showInformationMessage(transfer.message, 'Open', 'Reveal').then((pick) => {
          if (pick === 'Open') void vscode.commands.executeCommand('vscode.open', file);
          if (pick === 'Reveal') void vscode.commands.executeCommand('revealFileInOS', file);
        });
      } else if (transfer.state === 'cancelled') {
        void vscode.window.showInformationMessage(transfer.message);
      } else if (transfer.state !== 'running') {
        void vscode.window.showErrorMessage(transfer.message);
      }
    },
  };
}

/** `Download Log`: list, pick, then run the download under a cancellable progress notification. */
export function registerLogCommands(logs: LogListStore, downloads: LogDownloadService): vscode.Disposable[] {
  return [vscode.commands.registerCommand('px4Gcs.downloadLog', async () => {
    await logs.load();
    const state = logs.state;
    if (state.state === 'error') return void vscode.window.showErrorMessage(state.message);
    if (state.state !== 'done') return;
    if (!state.entries.length) return void vscode.window.showInformationMessage(NO_LOGS_TEXT);
    const pick = await vscode.window.showQuickPick(state.entries.map((entry) => ({
      label: `Log ${entry.id}`, description: formatBytes(entry.size), detail: logDate(entry.timeUtc), entry,
    })), { title: 'Download an onboard log', placeHolder: 'Pick a log' });
    if (!pick) return;
    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `Log ${pick.entry.id}`,
      cancellable: true }, async (progress, token) => {
      const cancel = token.onCancellationRequested(() => { void downloads.cancel(); });
      let shown = 0;
      const timer = setInterval(() => {
        const t = downloads.transfer;
        if (t?.state !== 'running' || t.logId !== pick.entry.id || !t.total) return;
        const percent = (100 * t.received) / t.total;
        progress.report({ message: transferText(t), increment: Math.max(percent - shown, 0) });
        shown = Math.max(shown, percent);
      }, 500);
      try {
        await downloads.download(pick.entry);
      } finally {
        clearInterval(timer);
        cancel.dispose();
      }
    });
  })];
}
