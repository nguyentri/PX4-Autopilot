import * as vscode from 'vscode';
import { BackendClient } from './backend-client';
import { ExecutionController, registerExecutionCommands } from './commands-execution';
import { registerSelectionCommands } from './commands-selection';
import { Px4NuttxDebugProvider } from './debug-provider';
import { SetupOperationToken } from './types';
import { SelectionStore } from './selection-store';
import { DualCoreLoaderController } from './dual-core-loader-controller';
import { FirmwareOutput } from './firmware-output';
import { RttMonitorViewProvider } from './rtt-monitor/rtt-monitor-view-provider';
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
  operationsView?: OperationsViewProvider,
  output?: FirmwareOutput,
  monitor?: RttMonitorViewProvider
): ExecutionController {
  registerSelectionCommands(context, client, store, selectionView, readinessView, artifactsView, operationsView);
  const execution = registerExecutionCommands(context, client, store, debugProvider, artifactsView, output);
  const dual = new DualCoreLoaderController(client, store, execution, monitor);
  monitor?.setSwitchHandler(async (core) => {
    try { await dual.switchRtt(core); } catch (error) { void vscode.window.showErrorMessage((error as Error).message); }
  });
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
    buildLoadTrace: () => dual.buildLoadTrace(),
    validate: () => dual.validate(), refresh: () => dual.validate(), resume: () => dual.resume(),
    keepCaptured: (core) => dual.keepCaptured(core), importUpdated: (core) => dual.importUpdated(core),
    loadBoth: () => dual.targetAction('load'), recoverBoth: () => dual.targetAction('recover'),
    debugSelected: () => dual.targetAction('debug', store.getSelectedCore() as 'cr8_0' | 'cr8_1'),
    loadAndDebug: () => dual.loadAndDebug(),
    debugR80: () => dual.targetAction('debug', 'cr8_0'), debugR81: () => dual.targetAction('debug', 'cr8_1'),
    startRtt: (core) => dual.startRtt(core), stopRtt: () => dual.stopRtt(),
    // The RTT bridge also holds the probe, so Stop Sessions frees it as well.
    stopSessions: async () => {
      await debugProvider.disposeAsync();
      store.notifySessionChange();
      if (store.getSelectedProbe()) { await dual.stopRtt(true); }
    },
  };
  const invoke = async (name: string, argument?: { setupId?: string; core?: 'cr8_0' | 'cr8_1'; token?: SetupOperationToken }): Promise<unknown> => {
    try {
      store.assertSetupOperationsReady();
      if (vscode.workspace.isTrusted === false) { throw new Error('Trust this workspace before using Firmware Setup.'); }
      if (argument?.setupId && argument.setupId !== store.getActiveSetup()?.id) { throw new Error('The clicked firmware setup is no longer active.'); }
      if (argument?.token && !store.isSetupTokenCurrent(argument.token)) { throw new Error('The clicked setup row changed. Refresh the view and choose it again.'); }
      const token = store.captureSetupToken(undefined, true);
      // A setup picker may wait while another operation changes inputs.
      if (['saveAs', 'rename', 'mode', 'select', 'probe'].includes(name)) { store.assertMutable(); }
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
