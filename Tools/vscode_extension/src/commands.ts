import * as vscode from 'vscode';
import { BackendClient } from './backend-client';
import { ExecutionController, registerExecutionCommands } from './commands-execution';
import { registerSelectionCommands } from './commands-selection';
import { Px4NuttxDebugProvider } from './debug-provider';
import { SetupOperationToken } from './types';
import { SelectionStore } from './selection-store';
import { DualCoreLoaderController } from './dual-core-loader-controller';
import {
  ArtifactsViewProvider,
  OperationsViewProvider,
  ReadinessViewProvider,
  SelectionViewProvider,
} from './workspace-view';

export function registerCommands(
  context: vscode.ExtensionContext,
  client: BackendClient,
  store: SelectionStore,
  selectionView: SelectionViewProvider,
  readinessView: ReadinessViewProvider,
  debugProvider: Px4NuttxDebugProvider,
  artifactsView: ArtifactsViewProvider,
  operationsView?: OperationsViewProvider
): ExecutionController {
  registerSelectionCommands(context, client, store, selectionView, readinessView, artifactsView, operationsView);
  const execution = registerExecutionCommands(context, client, store, debugProvider, artifactsView);
  const dual = new DualCoreLoaderController(client, store, execution);
  const actions: Record<string, (core?: 'cr8_0' | 'cr8_1') => Promise<unknown>> = {
    select: async () => {
      const token = store.captureSetupToken(undefined, true);
      const items = store.listSavedSetups().map((setup) => ({ label: setup.name, description: setup.selection.group, id: setup.id }));
      const picked = await vscode.window.showQuickPick([...items, { label: 'Choose another target / group…', id: '' }], { title: 'Firmware Setup', placeHolder: 'Select a saved setup or target' });
      if (!store.isSetupTokenCurrent(token)) { return; }
      if (picked?.id) { await store.activateSetup(picked.id); }
      else if (picked) { await vscode.commands.executeCommand('px4Nuttx.selectProfile'); }
    },
    saveAs: async () => { const token = store.captureSetupToken(undefined, true); const name = await vscode.window.showInputBox({ title: 'Save Firmware Setup As', prompt: 'Name this independent image variant' }); if (!store.isSetupTokenCurrent(token)) { return; } if (name !== undefined) { await store.saveActiveSetupAs(name); } },
    rename: async () => { const token = store.captureSetupToken(undefined, true); const name = await vscode.window.showInputBox({ title: 'Rename Firmware Setup', value: store.getActiveSetup()?.name }); if (!store.isSetupTokenCurrent(token)) { return; } if (name !== undefined) { await store.renameSetup(name); } },
    probe: async () => vscode.commands.executeCommand('px4Nuttx.selectProbe'),
    mode: async () => { const token = store.captureSetupToken(undefined, true); const mode = await vscode.window.showQuickPick(['incremental', 'clean'], { title: 'Build Mode' }); if (!store.isSetupTokenCurrent(token)) { return; } if (mode) { await store.setBuildMode(mode as 'incremental' | 'clean'); } },
    browse: (core) => dual.pickSource(core), folder: (core) => dual.pickSource(core, true), useBuild: (core) => dual.useBuild(core),
    cleanRebuild: () => dual.buildBoth(true),
    buildCore: (core) => dual.buildCore(core), buildBoth: () => dual.buildBoth(), buildAndLoad: () => dual.buildAndLoad(),
    validate: () => dual.validate(), refresh: () => dual.validate(), resume: () => dual.resume(),
    keepCaptured: (core) => dual.keepCaptured(core), importUpdated: (core) => dual.importUpdated(core),
    loadBoth: () => dual.targetAction('load'), recoverBoth: () => dual.targetAction('recover'),
    debugSelected: () => dual.targetAction('debug', store.getSelectedCore() as 'cr8_0' | 'cr8_1'),
    loadAndDebug: () => dual.loadAndDebug(),
    debugR80: () => dual.targetAction('debug', 'cr8_0'), debugR81: () => dual.targetAction('debug', 'cr8_1'),
    device: async (core) => {
      if (!core) { throw new Error('Choose a core console row.'); }
      const token = store.captureSetupToken(core, true);
      const device = await vscode.window.showInputBox({ title: 'SCI4 Device on Workspace Host', value: store.getConsoleDevice(core), prompt: 'For example /dev/serial/by-id/… (115200 8N1)' });
      if (!store.isSetupTokenCurrent(token)) { return; }
      if (device !== undefined) { await store.setSetupConsoleDevice(core, device); }
    },
    consoleCore: async (core) => {
      const starting = store.captureSetupToken(undefined, true);
      if (!core) {
        const picked = await vscode.window.showQuickPick(store.getGroupMembers().map((member) => ({ label: `${member.core} · ${store.getConsoleTransport(member.core).toUpperCase()}`, core: member.core })), { title: 'Open Core Console' });
        if (!store.isSetupTokenCurrent(starting)) { throw new Error('Setup changed while choosing a console core.'); }
        core = picked?.core as 'cr8_0' | 'cr8_1' | undefined;
      }
      if (!execution.startCoreConsole || !core) { return false; }
      const token = store.captureSetupToken(core, true);
      if (store.getConsoleTransport(core) === 'rtt' && !await dual.validate()) { throw new Error('Validate captured images before opening RTT.'); }
      if (!store.isSetupTokenCurrent(token)) { throw new Error('Setup changed before console startup.'); }
      return execution.startCoreConsole(core);
    },
    stopSessions: async () => { const results = await Promise.allSettled([execution.stopSessions?.(), debugProvider.disposeAsync()]); const failed = results.filter((r): r is PromiseRejectedResult => r.status === 'rejected'); if (failed.length) { throw new Error(failed.map((r) => String(r.reason)).join('; ')); } store.notifySessionChange(); },
  };
  const invoke = async (name: string, argument?: { setupId?: string; core?: 'cr8_0' | 'cr8_1'; token?: SetupOperationToken }): Promise<unknown> => {
    try {
      store.assertSetupOperationsReady();
      if (vscode.workspace.isTrusted === false) { throw new Error('Trust this workspace before using Firmware Setup.'); }
      if (argument?.setupId && argument.setupId !== store.getActiveSetup()?.id) { throw new Error('The clicked firmware setup is no longer active.'); }
      if (argument?.token && !store.isSetupTokenCurrent(argument.token)) { throw new Error('The clicked setup row changed. Refresh the view and choose it again.'); }
      const token = store.captureSetupToken(undefined, true);
      // A setup picker may wait while another operation changes inputs.
      if (['saveAs', 'rename', 'device', 'mode', 'select', 'probe'].includes(name)) { store.assertMutable(); }
      if (!store.isSetupTokenCurrent(token)) { return false; }
      return await actions[name](argument?.core);
    } catch (error) { void vscode.window.showErrorMessage((error as Error).message); return false; }
  };
  for (const name of Object.keys(actions)) {
    context.subscriptions.push(vscode.commands.registerCommand(`px4Nuttx.setup.${name}`, (argument) => invoke(name, argument)));
  }
  execution.setSetupRouter?.((name) => invoke(name));
  const refreshSetupContext = () => { void vscode.commands.executeCommand('setContext', 'px4Nuttx.savedSetupActive', !!store.getActiveSetup()); };
  context.subscriptions.push(store.onDidChangeSelection(refreshSetupContext)); refreshSetupContext();
  context.subscriptions.push(dual);
  store.setSetupOperationsReady(true);
  void vscode.commands.executeCommand('setContext', 'px4Nuttx.savedSetupOperationsReady', true);
  return execution;
}
