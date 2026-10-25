import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
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
} from './workspace-view';

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

async function chooseWorkspaceFolder(folders: readonly vscode.WorkspaceFolder[]): Promise<vscode.WorkspaceFolder | undefined> {
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
  const picked = await vscode.window.showQuickPick(items, {
    placeHolder: 'Select the firmware workspace for PX4/NuttX operations',
  });
  return picked?.folder;
}

async function initialize(context: vscode.ExtensionContext): Promise<void> {
  const folder = await chooseWorkspaceFolder(vscode.workspace.workspaceFolders || []);
  if (!folder) {
    return;
  }

  const rootPath = folder.uri.fsPath;
  const client = new BackendClient(rootPath);
  const store = new SelectionStore(context, rootPath);
  const statusBar = new StatusBarManager(store);
  statusBar.show();
  const selectionView = new SelectionViewProvider(store);
  const readinessView = new ReadinessViewProvider(client);
  const artifactsView = new ArtifactsViewProvider(rootPath, store);
  const operationsView = new OperationsViewProvider(store);
  const debugProvider = new Px4NuttxDebugProvider(client, store);
  debugProvider.registerLifecycle(context);
  const taskProvider = new Px4NuttxTaskProvider(rootPath, store, folder);

  activeClients.push(client);
  activeStores.push(store);
  activeDebugProviders.push(debugProvider);
  context.subscriptions.push(statusBar, debugProvider, store, client);

  context.subscriptions.push(
    vscode.window.registerTreeDataProvider('px4-nuttx.selection', selectionView),
    vscode.window.registerTreeDataProvider('px4-nuttx.readiness', readinessView),
    vscode.window.registerTreeDataProvider('px4-nuttx.artifacts', artifactsView),
    vscode.window.registerTreeDataProvider('px4-nuttx.operations', operationsView)
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
    operationsView
  );
  activeExecutionControllers.push(executionController);

  if (vscode.workspace.isTrusted) {
    void client.getCatalog().then((result) => {
      if (result.status === 'ok') {
        store.setCatalog(result.data);
        operationsView.refresh();
      }
    }).catch(() => {
      // The user can retry through Refresh; static selection state remains usable.
    });
    void client.runDoctor().then((result) => {
      if (result.data) {
        void readinessView.setDoctorData(result.data);
      }
    }).catch(() => {
      // Doctor is informational and must not make activation fail.
    });
  }

}

export function activate(context: vscode.ExtensionContext): void {
  void initialize(context);
}

export async function deactivate(): Promise<void> {
  for (const controller of activeExecutionControllers) {
    if (controller.disposeAsync) {
      await controller.disposeAsync();
    } else {
      controller.dispose();
    }
  }
  for (const provider of activeDebugProviders) {
    await provider.disposeAsync();
  }
  for (const client of activeClients) {
    client.dispose();
  }
  for (const store of activeStores) {
    store.dispose();
  }
  activeExecutionControllers.length = 0;
  activeDebugProviders.length = 0;
  activeClients.length = 0;
  activeStores.length = 0;
}

