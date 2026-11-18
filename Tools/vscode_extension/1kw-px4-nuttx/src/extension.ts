import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { FirmwareOutput } from './firmware-output';
import { RTT_MONITOR_VIEW, RttMonitorViewProvider } from './rtt-monitor/rtt-monitor-view-provider';
import { BackendClient } from './backend-client';
import { registerCommands } from './commands';
import { Px4NuttxDebugProvider } from './debug-provider';
import { SelectionStore } from './selection-store';
import { StatusBarManager } from './status';
import { Px4NuttxTaskProvider } from './task-provider';
import {
  ArtifactsViewProvider,
  OperationsViewProvider,
  ReadinessViewProvider,
  SelectionViewProvider,
  DualCoreLoaderViewProvider,
} from './workspace-view';

let lifecycle = 0;
let initialization: Promise<void> | undefined;
let activationCancellation: vscode.CancellationTokenSource | undefined;
let deactivation: Promise<void> | undefined;

const activeClients: BackendClient[] = [];
const activeStores: SelectionStore[] = [];
const activeDebugProviders: Px4NuttxDebugProvider[] = [];
const activeExecutionControllers: Array<{ dispose(): void; disposeAsync?: () => Promise<void> }> = [];

function isEligibleFolder(folder: vscode.WorkspaceFolder): boolean {
  const root = folder.uri.fsPath;
  return fs.existsSync(path.join(root, 'build.sh'))
    || fs.existsSync(path.join(root, 'Tools', 'firmware-workspace.py'))
    || fs.existsSync(path.join(root, 'platforms', 'nuttx', 'CMakeLists.txt'));
}

async function chooseWorkspaceFolder(folders: readonly vscode.WorkspaceFolder[], token: vscode.CancellationToken): Promise<vscode.WorkspaceFolder | undefined> {
  const eligible = folders.filter(isEligibleFolder);
  if (eligible.length === 0) {
    return undefined;
  }
  if (eligible.length === 1) {
    return eligible[0];
  }
  const items = eligible.map((folder) => ({
    label: `$(root-folder) ${folder.name}`,
    description: folder.uri.fsPath,
    folder,
  }));
  let cancel: vscode.Disposable | undefined;
  try {
    const picked = await Promise.race([
      vscode.window.showQuickPick(items, { placeHolder: 'Select the firmware workspace for PX4/NuttX operations' }, token),
      new Promise<undefined>((resolve) => { cancel = token.onCancellationRequested(() => resolve(undefined)); if (token.isCancellationRequested) { resolve(undefined); } }),
    ]);
    return picked?.folder;
  } finally { cancel?.dispose(); }
}

async function initialize(context: vscode.ExtensionContext, epoch: number, token: vscode.CancellationToken): Promise<void> {
  const folder = await chooseWorkspaceFolder(vscode.workspace.workspaceFolders || [], token);
  if (!folder || epoch !== lifecycle) {
    return;
  }

  const rootPath = folder.uri.fsPath;
  const client = new BackendClient(rootPath);
  const store = new SelectionStore(context, rootPath);
  const statusBar = new StatusBarManager(store);
  statusBar.show();
  const selectionView = new SelectionViewProvider(store, context.extensionUri);
  const readinessView = new ReadinessViewProvider(client);
  const artifactsView = new ArtifactsViewProvider(rootPath, store);
  const operationsView = new OperationsViewProvider(store);
  const dualCoreView = new DualCoreLoaderViewProvider(store);
  const debugProvider = new Px4NuttxDebugProvider(client, store);
  debugProvider.registerLifecycle(context);
  const taskProvider = new Px4NuttxTaskProvider(rootPath, store, folder);
  const firmwareOutput = new FirmwareOutput(rootPath);
  const rttMonitor = new RttMonitorViewProvider(context.extensionUri, rootPath,
    () => store.getActiveSetup()?.name || store.getSelection().id);

  activeClients.push(client);
  activeStores.push(store);
  activeDebugProviders.push(debugProvider);
  context.subscriptions.push(statusBar, debugProvider, store, client, dualCoreView, firmwareOutput, rttMonitor);

  context.subscriptions.push(
    vscode.window.registerTreeDataProvider('px4-nuttx.selection', selectionView),
    vscode.window.registerTreeDataProvider('px4-nuttx.readiness', readinessView),
    vscode.window.registerTreeDataProvider('px4-nuttx.artifacts', artifactsView),
    vscode.window.registerTreeDataProvider('px4-nuttx.operations', operationsView),
    vscode.window.registerTreeDataProvider('px4-nuttx.dualCoreLoader', dualCoreView),
    vscode.window.registerWebviewViewProvider(RTT_MONITOR_VIEW, rttMonitor, { webviewOptions: { retainContextWhenHidden: true } }),
    vscode.commands.registerCommand('px4Nuttx.rtt.show', () => rttMonitor.reveal()),
    vscode.commands.registerCommand('px4Nuttx.rtt.clear', () => rttMonitor.clear()),
    vscode.commands.registerCommand('px4Nuttx.rtt.copy', () => rttMonitor.copy()),
    vscode.commands.registerCommand('px4Nuttx.rtt.saveLog', () => rttMonitor.saveLog()),
    vscode.commands.registerCommand('px4Nuttx.rtt.toggleTimestamps', () => rttMonitor.toggleTimestamps())
  );
  context.subscriptions.push(
    vscode.debug.registerDebugConfigurationProvider('cortex-debug', debugProvider),
    vscode.tasks.registerTaskProvider(Px4NuttxTaskProvider.TaskType, taskProvider)
  );

  const executionController = registerCommands(
    context,
    client,
    store,
    selectionView,
    readinessView,
    debugProvider,
    artifactsView,
    operationsView,
    firmwareOutput,
    rttMonitor
  );
  activeExecutionControllers.push(executionController);
  void vscode.commands.executeCommand('setContext', 'px4Nuttx.workspaceReady', true);

  if (vscode.workspace.isTrusted) {
    await Promise.allSettled([client.getCatalog().then((result) => {
      if (epoch === lifecycle && result.status === 'ok') {
        store.setCatalog(result.data);
        operationsView.refresh();
      }
    }).catch(() => {
      // The user can retry through Refresh; static selection state remains usable.
    }), client.runDoctor().then((result) => {
      if (epoch === lifecycle && result.data) {
        void readinessView.setDoctorData(result.data);
      }
    }).catch(() => {
      // Doctor is informational and must not make activation fail.
    })]);
  }

}

export function activate(context: vscode.ExtensionContext): void {
  const epoch = ++lifecycle;
  void vscode.commands.executeCommand('setContext', 'px4Nuttx.workspaceReady', false);
  deactivation = undefined;
  activationCancellation?.dispose();
  activationCancellation = new vscode.CancellationTokenSource();
  initialization = initialize(context, epoch, activationCancellation.token).catch((error: Error) => {
    if (epoch === lifecycle) { void vscode.window.showErrorMessage(`Firmware workspace initialization failed: ${error.message}`); }
  });
}

export function deactivate(): Promise<void> {
  if (deactivation) { return deactivation; }
  ++lifecycle; activationCancellation?.cancel();
  void vscode.commands.executeCommand('setContext', 'px4Nuttx.workspaceReady', false);
  void vscode.commands.executeCommand('setContext', 'px4Nuttx.savedSetupOperationsReady', false);
  for (const store of activeStores) { store.shutdown(); }
  for (const provider of activeDebugProviders) { provider.shutdown(); }
  // Cancel backend build/import/discovery producers before joining initialization.
  for (const client of activeClients) { client.cancelOperations(); }
  deactivation = (async () => {
    await initialization;
    await Promise.allSettled(activeDebugProviders.map((provider) => provider.settleStarts()));
    const results = await Promise.allSettled([
      ...activeExecutionControllers.map((controller) => controller.disposeAsync ? controller.disposeAsync() : Promise.resolve(controller.dispose())),
      ...activeDebugProviders.map((provider) => provider.disposeAsync()),
      ...activeStores.map((store) => store.flushPersistence()),
    ]);
    const failures = results.filter((result): result is PromiseRejectedResult => result.status === 'rejected');
    // Retain failed owners. Releasing a client reservation while its owner is
    // uncertain would allow a second target session against the same probe.
    if (failures.length) { throw new Error(`Firmware cleanup incomplete: ${failures.map((r) => String(r.reason)).join('; ')}`); }
    for (const client of activeClients) { client.dispose(); }
    for (const store of activeStores) { store.dispose(); }
    activationCancellation?.dispose();
    activeExecutionControllers.length = activeDebugProviders.length = activeClients.length = activeStores.length = 0;
  })();
  return deactivation;
}
