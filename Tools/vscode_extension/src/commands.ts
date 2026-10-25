import * as vscode from 'vscode';
import { BackendClient } from './backend-client';
import { ExecutionController, registerExecutionCommands } from './commands-execution';
import { registerSelectionCommands } from './commands-selection';
import { Px4NuttxDebugProvider } from './debug-provider';
import { SelectionStore } from './selection-store';
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
  return registerExecutionCommands(context, client, store, debugProvider, artifactsView);
}
