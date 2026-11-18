// Entry point: one connection controller, its native views and commands.
// Everything that owns a process or a listener is disposed on deactivate.
import * as path from 'path';
import * as vscode from 'vscode';
import { LinkData } from './bridge/bridge-protocol';
import { ConnectionCommands } from './connection/connection-commands';
import { ConnectionController } from './connection/connection-controller';
import { describeError, showDescribedError } from './connection/connection-errors';
import { CONSOLE_ACCEPT } from './console/console-session';
import { confirmModal, registerControlCommands } from './control/control-commands';
import { DashboardPanel } from './dashboard/dashboard-panel';
import { DashboardRouter } from './dashboard/dashboard-router';
import { GcsOutput } from './gcs-output';
import { readGcsSettings } from './gcs-settings';
import { registerParameterCommands } from './parameters/parameter-commands';
import { SessionJournal } from './session/session-journal';
import { VehicleStateStore } from './vehicle/vehicle-state-store';
import { createLogHost, registerLogCommands } from './logs/log-commands';
import { RecordingStatusItem, registerSessionCommands } from './session/session-commands';
import { SessionJournalFeed } from './session/session-journal-feed';
import { SessionRecorder } from './session/session-recorder';
import { GcsStatusBar } from './views/gcs-status-bar';
import { VehicleTreeProvider } from './views/vehicle-tree-view';

let controller: ConnectionController | undefined;

export function activate(context: vscode.ExtensionContext): {
  controller: ConnectionController; router: DashboardRouter; journal: SessionJournal;
} {
  const output = new GcsOutput();
  const store = new VehicleStateStore();
  const pythonDir = path.join(context.extensionPath, 'python');
  const active = new ConnectionController({ pythonDir, store, log: (line) => output.log(line) });
  controller = active;
  const commands = new ConnectionCommands(context, active, output, pythonDir);
  const journal = new SessionJournal();
  const feed = new SessionJournalFeed(active, journal);
  // Recordings, reports and the log save dialog default to the setting, else the extension's global storage.
  const sessionsDir = (): string => readGcsSettings().recordingDirectory || context.globalStorageUri.fsPath;
  const recStatus = new RecordingStatusItem();
  const recorder = new SessionRecorder({ controller: active, journal, directory: sessionsDir, onState: (recording) => {
    recStatus.update(recording);
    tree.refresh();
    router.recordingChanged(recording); // runs only after activation, once `router` exists
  } });
  const tree = new VehicleTreeProvider(active, store, () => recorder.state);
  const router = new DashboardRouter({
    controller: active, store, journal,
    confirm: async (message) => (await vscode.window.showWarningMessage(message, { modal: true }, CONSOLE_ACCEPT))
      === CONSOLE_ACCEPT,
    confirmAction: confirmModal,
    controlEnabled: () => readGcsSettings().controlEnabled,
    runCommand: (command) => { void vscode.commands.executeCommand(`px4Gcs.${command}`); },
    copy: (text) => { void vscode.env.clipboard.writeText(text); },
    log: (line) => output.log(line),
    logHost: createLogHost(sessionsDir),
    recording: () => recorder.state,
  });
  const dashboard = new DashboardPanel(context.extensionUri, router);
  context.subscriptions.push(
    output,
    { dispose: () => store.dispose() },
    tree,
    vscode.window.createTreeView('px4Gcs.vehicle', { treeDataProvider: tree }),
    new GcsStatusBar(active, store),
    ...commands.register(),
    { dispose: () => router.dispose() },
    feed, recorder, recStatus,
    ...registerLogCommands(router.logs, router.downloads),
    ...registerSessionCommands({ recorder, feed, journal, directory: sessionsDir,
      extensionVersion: String(context.extension.packageJSON.version), log: (line) => output.log(line) }),
    dashboard,
    vscode.commands.registerCommand('px4Gcs.openDashboard', () => dashboard.open()),
    vscode.commands.registerCommand('px4Gcs.openConsole', () => dashboard.open('console')),
    ...registerControlCommands(router.commands),
    ...registerParameterCommands({
      context, controller: active, store, controlEnabled: () => readGcsSettings().controlEnabled,
      params: router.params, editor: router.editor, journal, log: (line) => output.log(line),
    }),
    active.onDidChangeState((state) => {
      void vscode.commands.executeCommand('setContext', 'px4Gcs.connected', state !== 'idle');
    }),
    active.onDidExitUnexpectedly((error) => {
      output.log(error.message);
      void showDescribedError(describeError(error, readGcsSettings().pythonPath));
    }),
    active.onEvent((event) => {
      if (event.name !== 'link') return;
      const link = event.data as unknown as LinkData;
      if (link.foreignFrames) {
        output.once('foreign', `ignoring frames from systems other than ${link.systemId} (${link.foreignFrames} so far)`);
      }
      if (link.droppedEvents > 0) output.log(`sidecar dropped ${link.droppedEvents} events (host too slow)`);
    }),
  );
  return { controller: active, router, journal };
}

/** VS Code awaits this promise: the sidecar is stopped before the host goes away. */
export async function deactivate(): Promise<void> {
  const active = controller;
  controller = undefined;
  await active?.dispose();
}
