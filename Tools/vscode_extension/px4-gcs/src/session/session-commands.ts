// VS Code plumbing for recordings and the session report: the recording
// status bar item, the commands Start/Stop Recording, Open Session Report and
// Reveal Sessions Folder, and the report offer when a recording stops.
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { RecordingView } from '../dashboard/dashboard-messages';
import { SessionJournal } from './session-journal';
import { SessionJournalFeed } from './session-journal-feed';
import { SessionRecorder } from './session-recorder';
import { buildSessionReport } from './session-report-builder';

export interface SessionCommandOptions {
  recorder: SessionRecorder;
  feed: SessionJournalFeed;
  journal: SessionJournal;
  directory(): string;
  extensionVersion: string;
  log(line: string): void;
}

const message = (error: unknown): string => (error instanceof Error ? error.message : String(error));

/** Write the report next to the recordings and open it in the system browser. */
export async function writeSessionReport(options: SessionCommandOptions): Promise<string> {
  const generated = new Date();
  const html = buildSessionReport({ journal: options.journal, statistics: options.feed.statistics,
    started: options.feed.started, generated, extensionVersion: options.extensionVersion });
  const folder = options.directory();
  await fs.promises.mkdir(folder, { recursive: true });
  const stamp = generated.toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
  const file = path.join(folder, `px4-gcs-report-${stamp}.html`);
  await fs.promises.writeFile(file, html, { encoding: 'utf8', flag: 'wx' });
  return file;
}

export class RecordingStatusItem implements vscode.Disposable {
  private readonly item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 49);

  update(recording: RecordingView): void {
    if (!recording.active) return void this.item.hide();
    this.item.text = '$(record) REC';
    this.item.tooltip = `Recording to ${recording.path ?? ''}. Click to stop.`;
    this.item.command = 'px4Gcs.stopRecording';
    this.item.backgroundColor = new vscode.ThemeColor('statusBarItem.errorBackground');
    this.item.show();
  }

  dispose(): void {
    this.item.dispose();
  }
}

export function registerSessionCommands(options: SessionCommandOptions): vscode.Disposable[] {
  const openReport = async (): Promise<void> => {
    try {
      const file = await writeSessionReport(options);
      options.log(`session report: ${file}`);
      await vscode.env.openExternal(vscode.Uri.file(file));
    } catch (error) {
      void vscode.window.showErrorMessage(`Session report not written: ${message(error)}`);
    }
  };
  return [
    vscode.commands.registerCommand('px4Gcs.startRecording', async () => {
      try {
        const file = await options.recorder.start();
        options.log(`recording to ${file}`);
      } catch (error) {
        void vscode.window.showErrorMessage(`Recording not started: ${message(error)}`);
      }
    }),
    vscode.commands.registerCommand('px4Gcs.stopRecording', async () => {
      try {
        if (!(await options.recorder.stop())) void vscode.window.showInformationMessage('No recording is running.');
      } catch (error) {
        void vscode.window.showErrorMessage(`Recording not stopped: ${message(error)}`);
      }
    }),
    vscode.commands.registerCommand('px4Gcs.openSessionReport', openReport),
    vscode.commands.registerCommand('px4Gcs.revealSessions', async () => {
      const folder = options.directory();
      await fs.promises.mkdir(folder, { recursive: true });
      await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(folder));
    }),
    // Offer the report whenever a recording ends (operator stop or disconnect).
    options.journal.onDidAppend((entry) => {
      if (entry.kind !== 'recording' || entry.data.state !== 'stopped') return;
      const where = typeof entry.data.path === 'string' ? path.basename(entry.data.path) : 'the recording';
      void vscode.window.showInformationMessage(`Recording stopped (${String(entry.data.reason)}): ${where}.`,
        'Open Session Report', 'Reveal').then((pick) => {
        if (pick === 'Open Session Report') void openReport();
        if (pick === 'Reveal' && typeof entry.data.path === 'string') {
          void vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(entry.data.path));
        }
      });
    }),
  ];
}
