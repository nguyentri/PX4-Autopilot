import * as vscode from 'vscode';
import { BackendClient, ConsoleOptions, LoadOptions, ProbeLeaseHandle, WorkspaceTrustError } from './backend-client';
import { Px4NuttxDebugProvider } from './debug-provider';
import { SelectionStore } from './selection-store';
import { ConsoleHandoff, FirmwareSelection, OperationResult } from './types';
import { ArtifactsViewProvider } from './workspace-view';

interface OperationSnapshot {
  selection: FirmwareSelection;
  selectionPath: string;
  receiptPath: string | null;
  core: string;
  serial: string;
}

interface ConsoleState {
  snapshot: OperationSnapshot;
  lease: ProbeLeaseHandle;
  core: string;
  transport: string;
}

export interface ExecutionController extends vscode.Disposable {
  stopConsoleForHandoff(): Promise<ConsoleHandoff>;
  disposeAsync(): Promise<void>;
}

function trusted(): boolean {
  return vscode.workspace?.isTrusted !== false;
}

function diagnostics(result: OperationResult<any>): string {
  return result.diagnostics?.map((diagnostic) => diagnostic.message).join('; ') || 'operation was blocked';
}

function selectionEquals(left: FirmwareSelection, right: FirmwareSelection): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function operationResultOk(result: OperationResult<any> | null | undefined): boolean {
  return result?.status === 'ok'
    && result.data?.recoveryRequired !== true
    && result.data?.state !== 'indeterminate'
    && result.data?.state !== 'recovery-required';
}

export function registerExecutionCommands(
  context: vscode.ExtensionContext,
  client: BackendClient,
  store: SelectionStore,
  debugProvider: Px4NuttxDebugProvider,
  artifactsView: ArtifactsViewProvider
): ExecutionController {
  let activeConsole: ConsoleState | null = null;
  let handoffLease: ProbeLeaseHandle | null = null;

  const receiptFor = (selection: FirmwareSelection): string | null => {
    return store.getReceiptPath(selection);
  };

  const bindReceipt = (receiptPath: string | null, selection: FirmwareSelection): void => {
    store.setReceiptPath(receiptPath, selection);
  };

  const selectionPathFor = (selection: FirmwareSelection): string => {
    return store.writeSelectionSnapshot(selection);
  };

  const snapshot = (selection: FirmwareSelection = store.getSelection()): OperationSnapshot => ({
    selection,
    selectionPath: selectionPathFor(selection),
    receiptPath: receiptFor(selection),
    core: store.getSelectedCore(),
    serial: store.getSelectedProbe(),
  });

  const selectionStillCurrent = (operation: OperationSnapshot): boolean =>
    selectionEquals(operation.selection, store.getSelection())
      && operation.core === store.getSelectedCore()
      && operation.serial === store.getSelectedProbe();

  let acquireProbeLease: (operation: OperationSnapshot) => Promise<ProbeLeaseHandle | null>;

  const showTrustError = (operation: string): false => {
    vscode.window.showErrorMessage(`Workspace trust is required to ${operation}.`);
    return false;
  };

  const showResultError = (label: string, result: OperationResult<any>): false => {
    const suffix = result.data?.recoveryRequired ? ' Recovery is required before another ordinary load.' : '';
    const prefix = result.status === 'cancelled' ? `${label} cancelled` : label;
    vscode.window.showErrorMessage(`${prefix}: ${diagnostics(result)}${suffix}`);
    return false;
  };

  const runBuild = async (clean = false): Promise<boolean> => {
    if (!trusted()) {
      return showTrustError('build firmware');
    }
    const operation = snapshot();
    return vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: clean ? 'Cleaning and building firmware...' : 'Building firmware...',
        cancellable: true,
      },
      async (progress, token) => {
        try {
          const result = await client.buildSelection(operation.selectionPath, {
            clean,
            cancellationToken: token,
            onOutput: (chunk) => {
              const message = chunk.trim().split(/\r?\n/).filter(Boolean).pop();
              if (message) {
                progress.report({ message: message.slice(-240) });
              }
            },
          });
          if (!operationResultOk(result) || !result.receiptPath) {
            return showResultError(clean ? 'Clean rebuild failed' : 'Build failed', result);
          }
          bindReceipt(result.receiptPath, operation.selection);
          artifactsView.refresh();
          vscode.window.showInformationMessage(`${clean ? 'Clean rebuild' : 'Build'} completed for ${operation.selection.id}.`);
          return true;
        } catch (error) {
          const message = error instanceof WorkspaceTrustError ? error.message : (error as Error).message;
          vscode.window.showErrorMessage(`${clean ? 'Clean rebuild' : 'Build'} failed: ${message}`);
          return false;
        }
      }
    );
  };

  const runLoad = async (
    operation: OperationSnapshot,
    recover = false,
    retainedLease?: ProbeLeaseHandle
  ): Promise<OperationResult<any> | null> => {
    if (!trusted()) {
      showTrustError('load firmware to a target');
      return null;
    }
    const receiptPath = receiptFor(operation.selection);
    if (!receiptPath) {
      const choice = await vscode.window.showWarningMessage(
        'No committed receipt matches the selected profile. Build it before loading.',
        'Build Target'
      );
      if (choice === 'Build Target' && await runBuild()) {
        if (!selectionStillCurrent(operation)) {
          await retainedLease?.release().catch(() => undefined);
          vscode.window.showErrorMessage('The selection changed while building; target loading was cancelled.');
          return null;
        }
        return runLoad({ ...operation, receiptPath: receiptFor(operation.selection) }, recover, retainedLease);
      }
      await retainedLease?.release().catch(() => undefined);
      return null;
    }
    const options: LoadOptions = {
      recover,
    };
    const lease = retainedLease || await acquireProbeLease(operation);
    if (!lease) {
      return null;
    }
    try {
      const result = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: recover ? 'Running guarded recovery load...' : 'Loading selected ELF to RAM...',
          cancellable: true,
        },
        async (progress, token) => client.loadTarget(operation.selectionPath, receiptPath, operation.serial, {
          ...options,
          lease: lease.lease,
          cancellationToken: token,
          onOutput: (chunk) => {
            const message = chunk.trim().split(/\r?\n/).filter(Boolean).pop();
            if (message) {
              progress.report({ message: message.slice(-240) });
            }
          },
        })
      );
      if (!operationResultOk(result)) {
        showResultError(recover ? 'Recovery load failed' : 'Load failed', result);
        await lease.release().catch(() => undefined);
        return result;
      }
      if (!retainedLease) {
        await lease.release().catch((error: Error) => {
          vscode.window.showWarningMessage(`Probe reservation cleanup is still pending: ${error.message}`);
        });
      }
      vscode.window.showInformationMessage(recover ? 'Recovery load completed.' : 'Selected ELF loaded to RAM and verified.');
      return result;
    } catch (error) {
      await lease.release().catch(() => undefined);
      const message = error instanceof WorkspaceTrustError ? error.message : (error as Error).message;
      vscode.window.showErrorMessage(`Load failed: ${message}`);
      return null;
    }
  };

  const stopConsoleInternal = async (notify = true, preserveLease = false): Promise<boolean> => {
    if (!activeConsole) {
      return true;
    }
    const state = activeConsole;
    const receiptPath = receiptFor(state.snapshot.selection) || state.snapshot.receiptPath;
    if (!receiptPath) {
      vscode.window.showErrorMessage('Cannot stop the console because its bound receipt is no longer available.');
      return false;
    }
    try {
      const result = await client.consoleAction(
        'stop',
        state.snapshot.selectionPath,
        receiptPath,
        state.lease.lease.serial,
        { core: state.core, lease: state.lease.lease }
      );
      if (!operationResultOk(result)) {
        if (notify) {
          showResultError('Console stop failed', result);
        }
        return false;
      }
      if (preserveLease) {
        handoffLease = state.lease;
      } else {
        await state.lease.release();
      }
      activeConsole = null;
      if (notify) {
        vscode.window.showInformationMessage('Console stopped.');
      }
      return true;
    } catch (error) {
      if (notify) {
        vscode.window.showErrorMessage(`Console stop failed: ${(error as Error).message}`);
      }
      return false;
    }
  };

  acquireProbeLease = async (operation: OperationSnapshot): Promise<ProbeLeaseHandle | null> => {
    if (!operation.serial) {
      vscode.window.showErrorMessage('Select a J-Link probe before starting a target operation.');
      return null;
    }
    if (activeConsole && !(await stopConsoleInternal(false, true))) {
      vscode.window.showErrorMessage('Stop the active console before starting another target operation.');
      return null;
    }
    if (handoffLease) {
      const lease = handoffLease;
      handoffLease = null;
      return lease;
    }
    return client.probeLeases.acquire(operation.serial).catch((error: Error) => {
      vscode.window.showErrorMessage(`Unable to reserve probe ${operation.serial}: ${error.message}`);
      return null;
    });
  };

  const startConsole = async (): Promise<boolean> => {
    if (!trusted()) {
      return showTrustError('start the console');
    }
    const operation = snapshot();
    const receiptPath = receiptFor(operation.selection);
    if (!receiptPath) {
      vscode.window.showWarningMessage('Build the selected profile before starting its console.');
      return false;
    }
    const core = operation.core;
    const transport = store.getConsoleTransport(core);
    if (operation.selection.board !== 'rdk-rzv2h' || (core !== 'cr8_0' && core !== 'cr8_1')) {
      vscode.window.showErrorMessage(`Managed console ownership is unavailable for ${operation.selection.board}:${core}; use the documented manual console route.`);
      return false;
    }
    if (transport === 'none') {
      vscode.window.showErrorMessage(`No supported console transport is configured for ${core}.`);
      return false;
    }
    if (transport !== 'rtt') {
      vscode.window.showErrorMessage(`${transport.toUpperCase()} console is not managed by the extension. Use platforms/nuttx/Debug/nsh_console_exec.py with the selected serial.`);
      return false;
    }
    if (!operation.selection.group && operation.selection.build.family === 'px4') {
      const receipt = store.readReceipt(receiptPath) as { artifacts?: Array<{ core?: string; rttAddress?: string | null }> } | null;
      const artifact = receipt?.artifacts?.find((item) => item.core === core || (!item.core && core === operation.selection.core));
      if (!artifact?.rttAddress) {
        vscode.window.showErrorMessage(`No RTT control block is admitted for ${core}; use the documented manual console route.`);
        return false;
      }
    }
    if (activeConsole && !(await stopConsoleInternal(false))) {
      vscode.window.showErrorMessage('Stop the active console before starting another one.');
      return false;
    }
    if (handoffLease) {
      const staleHandoff = handoffLease;
      handoffLease = null;
      try {
        await staleHandoff.release();
      } catch (error) {
        vscode.window.showErrorMessage(`Previous probe handoff is still active: ${(error as Error).message}`);
        return false;
      }
    }
    const serial = operation.serial;
    if (!serial) {
      vscode.window.showErrorMessage('Select a J-Link probe before starting the console.');
      return false;
    }

    const lease = await client.probeLeases.acquire(serial).catch((error: Error) => {
      vscode.window.showErrorMessage(`Unable to reserve probe ${serial}: ${error.message}`);
      return null;
    });
    if (!lease) {
      return false;
    }
    const options: ConsoleOptions = { core, lease: lease.lease };
    try {
      const result = await client.consoleAction('start', operation.selectionPath, receiptPath, serial, options);
      if (!operationResultOk(result)) {
        await lease.release().catch((error: Error) => {
          vscode.window.showWarningMessage(`Probe reservation cleanup is still pending: ${error.message}`);
        });
        return showResultError('Console start failed', result);
      }
      activeConsole = { snapshot: { ...operation, receiptPath }, lease, core, transport };
      vscode.window.showInformationMessage(`${transport.toUpperCase()} console started on ${core}.`);
      return true;
    } catch (error) {
      await lease.release().catch((releaseError: Error) => {
        vscode.window.showWarningMessage(`Probe reservation cleanup is still pending: ${releaseError.message}`);
      });
      vscode.window.showErrorMessage(`Console start failed: ${(error as Error).message}`);
      return false;
    }
  };

  context.subscriptions.push(
    vscode.commands.registerCommand('px4Nuttx.build', () => runBuild(false)),
    vscode.commands.registerCommand('px4Nuttx.cleanRebuild', () => runBuild(true)),
    vscode.commands.registerCommand('px4Nuttx.load', async () => {
      if (!trusted()) {
        showTrustError('load firmware to a target');
        return false;
      }
      const operation = snapshot();
      const result = await runLoad(operation, false);
      return operationResultOk(result);
    }),
    vscode.commands.registerCommand('px4Nuttx.recoverLoad', async () => {
      if (!trusted()) {
        showTrustError('run guarded recovery');
        return false;
      }
      const result = await runLoad(snapshot(), true);
      return operationResultOk(result);
    }),
    vscode.commands.registerCommand('px4Nuttx.attach', async () => {
      if (!trusted()) {
        showTrustError('attach the debugger');
        return false;
      }
      let operation = snapshot();
      let receiptPath = receiptFor(operation.selection);
      if (!receiptPath) {
        const choice = await vscode.window.showWarningMessage('Build the selected profile before debugging.', 'Build Target');
        if (choice !== 'Build Target' || !(await runBuild())) {
          return false;
        }
        if (!selectionStillCurrent(operation)) {
          vscode.window.showErrorMessage('The selection changed while building; debugger attach was cancelled.');
          return false;
        }
        receiptPath = receiptFor(operation.selection);
      }
      if (!receiptPath) {
        return false;
      }
      const started = await debugProvider.startManagedAttach(receiptPath, operation.core, operation.selection, operation.serial);
      return started;
    }),
    vscode.commands.registerCommand('px4Nuttx.loadAndDebug', async () => {
      if (!trusted()) {
        showTrustError('load and debug firmware');
        return false;
      }
      let operation = snapshot();
      if (!receiptFor(operation.selection)) {
        if (!(await runBuild())) {
          return false;
        }
        if (!selectionStillCurrent(operation)) {
          vscode.window.showErrorMessage('The selection changed while building; Load and Debug was cancelled.');
          return false;
        }
      }
      const lease = await acquireProbeLease(operation);
      if (!lease) {
        return false;
      }
      const loaded = await runLoad(operation, false, lease);
      if (!operationResultOk(loaded)) {
        return false;
      }
      const receiptPath = receiptFor(operation.selection);
      if (!receiptPath
        || !selectionEquals(operation.selection, store.getSelection())
        || operation.core !== store.getSelectedCore()
        || operation.serial !== store.getSelectedProbe()) {
        await lease.release().catch(() => undefined);
        vscode.window.showErrorMessage('The firmware selection changed while loading; debugger attach was cancelled.');
        return false;
      }
      try {
        return await debugProvider.startManagedAttach(receiptPath, operation.core, operation.selection, operation.serial, lease);
      } catch (error) {
        await lease.release().catch(() => undefined);
        vscode.window.showErrorMessage(`Failed starting managed debugger: ${(error as Error).message}`);
        return false;
      }
    }),
    vscode.commands.registerCommand('px4Nuttx.startConsole', startConsole),
    vscode.commands.registerCommand('px4Nuttx.stopConsole', () => stopConsoleInternal(true))
  );

  const disposeAsync = async (): Promise<void> => {
    if (!(await stopConsoleInternal(false))) {
      throw new Error('Owned console did not acknowledge teardown; probe reservation remains active.');
    }
    if (handoffLease) {
      const lease = handoffLease;
      handoffLease = null;
      await lease.release();
    }
  };

  const controller: ExecutionController = {
    stopConsoleForHandoff: async (): Promise<ConsoleHandoff> => {
      const ok = await stopConsoleInternal(false, true);
      const lease = ok ? handoffLease || undefined : undefined;
      handoffLease = null;
      return { ok, lease };
    },
    disposeAsync,
    dispose: () => {
      void disposeAsync().catch((error: Error) => {
        vscode.window.showErrorMessage(`Firmware session cleanup failed: ${error.message}`);
      });
    },
  };
  debugProvider.setConsoleHandoff(controller.stopConsoleForHandoff);
  return controller;
}

