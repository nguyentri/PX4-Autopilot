import * as vscode from 'vscode';
import { BackendClient, LoadOptions, ProbeLeaseHandle, WorkspaceTrustError } from './backend-client';
import { Px4NuttxDebugProvider } from './debug-provider';
import { SelectionStore } from './selection-store';
import { FirmwareSelection, OperationResult, PreparedExecutionRequest, R8Core } from './types';
import { ArtifactsViewProvider } from './workspace-view';
import { FirmwareOutput } from './firmware-output';

interface OperationSnapshot {
  selection: FirmwareSelection;
  selectionPath: string;
  receiptPath: string | null;
  core: string;
  serial: string;
}

export interface ExecutionController extends vscode.Disposable {
  buildSelectedGroup(selection: FirmwareSelection, clean?: boolean): Promise<OperationResult | null>;
  buildExact(selection: FirmwareSelection, clean?: boolean, cancellationToken?: vscode.CancellationToken): Promise<OperationResult | null>;
  setSetupRouter?(router: (name: string) => Promise<unknown>): void;
  loadPrepared(request: PreparedExecutionRequest, options: { recover: boolean; allowImplicitBuild: false; retainedLease?: ProbeLeaseHandle }): Promise<OperationResult | null>;
  debugPrepared(request: PreparedExecutionRequest, core: R8Core, options: { requireLoaded: true; retainedLease?: ProbeLeaseHandle }): Promise<boolean>;
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
  artifactsView: ArtifactsViewProvider,
  output?: FirmwareOutput
): ExecutionController {
  let setupRouter: ((name: string) => Promise<unknown>) | undefined;
  const routes: Record<string, string> = { 'px4Nuttx.build': 'buildBoth', 'px4Nuttx.cleanRebuild': 'cleanRebuild', 'px4Nuttx.load': 'loadBoth',
    'px4Nuttx.attach': 'debugSelected', 'px4Nuttx.loadAndDebug': 'loadAndDebug', 'px4Nuttx.recoverLoad': 'recoverBoth' };
  const register = (name: string, handler: (...args: any[]) => unknown) => vscode.commands.registerCommand(name, (...args: any[]) => {
    if (store.getActiveSetup?.() && setupRouter && routes[name]) { return setupRouter(routes[name]); }
    return handler(...args);
  });
  // Consoles are manual (serial terminal or nuttx-rtt-bridge.sh); only the
  // debugger owns sessions here.
  store.setSessionGuard(() => debugProvider.hasOwnedSessions());

  const receiptFor = (selection: FirmwareSelection): string | null => {
    return store.getReceiptPath(selection);
  };

  const bindReceipt = async (receiptPath: string | null, selection: FirmwareSelection): Promise<void> => {
    await store.setReceiptPath(receiptPath, selection);
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

  let acquireProbeLease: (operation: OperationSnapshot) => Promise<ProbeLeaseHandle | null>;

  const showTrustError = (operation: string): false => {
    vscode.window.showErrorMessage(`Workspace trust is required to ${operation}.`);
    return false;
  };

  const showResultError = (label: string, result: OperationResult<any>): false => {
    const suffix = result.data?.recoveryRequired ? ' Recovery is required before another ordinary load.' : '';
    const prefix = result.status === 'cancelled' ? `${label} cancelled` : label;
    const step = result.data?.steps?.slice().reverse().find((item: { state: string }) => ['fail', 'indeterminate'].includes(item.state));
    const detail = step ? ` R8-${step.core.slice(-1)} ${step.phase}: ${step.state}.` : '';
    const logs = result.data?.logPath ? ` Logs: ${result.data.logPath}` : '';
    vscode.window.showErrorMessage(`${prefix}: ${diagnostics(result)}${detail}${suffix}${logs}`);
    return false;
  };

  const runBuildResult = async (selection: FirmwareSelection, clean = false, bind = true, cancellationToken?: vscode.CancellationToken): Promise<OperationResult | null> => {
    if (store.getTargetTransition?.()) { vscode.window.showErrorMessage('Wait for the active target operation to finish before building.'); return null; }
    if (!trusted()) {
      showTrustError('build firmware'); return null;
    }
    const operation = snapshot(selection);
    const label = `${clean ? 'Clean rebuild' : 'Build'} ${operation.selection.id}`;
    output?.beginBuild(label);
    // The full log goes to the Output channel; a failure offers its Problems.
    const offerLog = async (message: string): Promise<void> => {
      output?.finishBuild(false, label);
      const actions = output ? (output.problemCount() ? ['Show Problems', 'Show Log'] : ['Show Log']) : [];
      const choice = await vscode.window.showErrorMessage(message, ...actions);
      if (choice === 'Show Problems') { await vscode.commands.executeCommand('workbench.actions.view.problems'); }
      if (choice === 'Show Log') { output?.show(); }
    };
    return vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: clean ? 'Cleaning and building firmware...' : 'Building firmware...',
        cancellable: !cancellationToken,
      },
      async (progress, token) => {
        try {
          const result = await client.buildSelection(operation.selectionPath, {
            clean,
            cancellationToken: cancellationToken || token,
            onOutput: (chunk) => {
              output?.appendBuild(chunk);
              const message = chunk.trim().split(/\r?\n/).filter(Boolean).pop();
              if (message) {
                progress.report({ message: message.slice(-240) });
              }
            },
          });
          if (!operationResultOk(result) || !result.receiptPath) {
            if (output) {
              const logs = result.data?.logPath ? ` Logs: ${result.data.logPath}` : '';
              void offerLog(`${clean ? 'Clean rebuild failed' : 'Build failed'}: ${diagnostics(result)}${logs}`);
            } else { showResultError(clean ? 'Clean rebuild failed' : 'Build failed', result); }
            return result;
          }
          output?.finishBuild(true, label);
          if (bind) { await bindReceipt(result.receiptPath, operation.selection); }
          artifactsView.refresh();
          vscode.window.showInformationMessage(`${clean ? 'Clean rebuild' : 'Build'} completed for ${operation.selection.id}.`);
          return result;
        } catch (error) {
          const message = error instanceof WorkspaceTrustError ? error.message : (error as Error).message;
          if (output) { void offerLog(`${clean ? 'Clean rebuild' : 'Build'} failed: ${message}`); }
          else { vscode.window.showErrorMessage(`${clean ? 'Clean rebuild' : 'Build'} failed: ${message}`); }
          return null;
        }
      }
    );
  };

  const runBuild = async (clean = false): Promise<boolean> => operationResultOk(await runBuildResult(store.getSelection(), clean));

  const runLoad = async (
    operation: OperationSnapshot,
    recover = false,
    retainedLease?: ProbeLeaseHandle,
    prepared?: PreparedExecutionRequest
  ): Promise<OperationResult<any> | null> => {
    if (!prepared && store.getTargetTransition?.()) {
      vscode.window.showErrorMessage('Wait for the active target operation to finish.'); return null;
    }
    if (!trusted()) {
      showTrustError('load firmware to a target');
      return null;
    }
    const receiptPath = prepared ? prepared.receiptPath : receiptFor(operation.selection);
    if (prepared && !preparedCurrent(prepared)) { await retainedLease?.release().catch(() => undefined); return null; }
    if (!receiptPath) {
      const choice = await vscode.window.showWarningMessage(
        'No committed receipt matches the selected profile. Build it, then choose Load again.',
        'Build Target'
      );
      if (choice === 'Build Target') { await runBuild(); }
      await retainedLease?.release().catch(() => undefined);
      return null;
    }
    const options: LoadOptions = {
      recover,
      expectReceiptId: prepared?.receiptId, expectPairSha256: prepared?.pairSha256, operationInstanceId: prepared?.operationInstanceId,
    };
    const lease = retainedLease || await acquireProbeLease(operation);
    if (!lease) {
      return null;
    }
    try {
      if (prepared && (!preparedCurrent(prepared) || lease.lease.serial !== prepared.serial)) {
        await lease.release(); throw new Error('Prepared pair changed during probe handoff; load cancelled.');
      }
      const result = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: recover ? 'Running guarded recovery load...' : 'Loading selected ELF to RAM...',
          cancellable: !prepared?.workflowCancellation,
        },
        async (progress, token) => {
          if (prepared) { progress.report({ message: 'Checking images' }); }
          const result = await client.loadTarget(operation.selectionPath, receiptPath, operation.serial, {
          ...options,
          lease: lease.lease,
          cancellationToken: prepared?.workflowCancellation || token,
          onProgress: prepared ? (event) => progress.report({ message: `${event.phase === 'load' ? 'Loading' : 'Verifying pair:'} R8-${event.core.slice(-1)}: ${event.state}` }) : undefined,
          onOutput: prepared ? undefined : (chunk) => {
            const message = chunk.trim().split(/\r?\n/).filter(Boolean).pop();
            if (message) {
              progress.report({ message: message.slice(-240) });
            }
          },
          });
          if (prepared && operationResultOk(result)) { progress.report({ message: 'Completed' }); }
          return result;
        }
      );
      if (prepared && operationResultOk(result) && !resultMatches(prepared, result)) {
        await lease.release(); throw new Error('Load result identity differs from the prepared request; inspect the operation logs before recovery.');
      }
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

  acquireProbeLease = async (operation: OperationSnapshot): Promise<ProbeLeaseHandle | null> => {
    if (!operation.serial) { vscode.window.showErrorMessage('Select a J-Link probe before starting a target operation.'); return null; }
    return client.probeLeases.acquire(operation.serial).catch((error: Error) => {
      vscode.window.showErrorMessage(`Unable to reserve probe ${operation.serial}: ${error.message}`); return null;
    });
  };
  context.subscriptions.push(
    register('px4Nuttx.build', () => runBuild(false)),
    register('px4Nuttx.cleanRebuild', () => runBuild(true)),
    register('px4Nuttx.load', async () => {
      if (!trusted()) {
        showTrustError('load firmware to a target');
        return false;
      }
      const operation = snapshot();
      const result = await runLoad(operation, false);
      return operationResultOk(result);
    }),
    register('px4Nuttx.recoverLoad', async () => {
      if (!trusted()) {
        showTrustError('run guarded recovery');
        return false;
      }
      const result = await runLoad(snapshot(), true);
      return operationResultOk(result);
    }),
    register('px4Nuttx.attach', async () => {
      if (!trusted()) {
        showTrustError('attach the debugger');
        return false;
      }
      const operation = snapshot();
      const receiptPath = receiptFor(operation.selection);
      if (!receiptPath) {
        const choice = await vscode.window.showWarningMessage('Build the selected profile, then choose Attach Debugger again.', 'Build Target');
        if (choice === 'Build Target') { await runBuild(); }
        return false;
      }
      const started = await debugProvider.startManagedAttach(receiptPath, operation.core, operation.selection, operation.serial);
      return started;
    }),
    register('px4Nuttx.loadAndDebug', async () => {
      if (!trusted()) {
        showTrustError('load and debug firmware');
        return false;
      }
      const operation = snapshot();
      if (!receiptFor(operation.selection)) {
        const choice = await vscode.window.showWarningMessage('Build the selected profile, then choose Load and Debug again.', 'Build Target');
        if (choice === 'Build Target') { await runBuild(); }
        return false;
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
    })
  );

  const disposeAsync = async (): Promise<void> => undefined;

  const preparedCurrent = (request: PreparedExecutionRequest): boolean => {
    const state = store.getPreparedPair(request.selection.group);
    return (!request.setupToken || store.isSetupTokenCurrent(request.setupToken)) && store.getSelectionIdentity(request.selection) === store.getSelectionIdentity()
      && store.getSelectedProbe() === request.serial && state?.generation === request.pairGeneration
      && !state.pending && !state.validationError && !Object.keys(state.sourceChanges || {}).length
      && state.prepared?.receiptId === request.receiptId && state.prepared.receiptPath === request.receiptPath
      && state.prepared.pairSha256 === request.pairSha256
      && state.prepared.artifacts.every((artifact) => artifact.sha256 === request.artifactDigests[artifact.core as R8Core]);
  };
  const resultMatches = (request: PreparedExecutionRequest, result: OperationResult): boolean =>
    result.data.receiptId === request.receiptId && result.data.pairSha256 === request.pairSha256
    && result.data.operationInstanceId === request.operationInstanceId
    && result.data.groupDefinitionSha256 === request.groupDefinitionSha256
    && Object.entries(request.artifactDigests).every(([core, digest]) => result.data.artifactDigests?.[core] === digest);

  const controller: ExecutionController = {
    setSetupRouter: (router) => { setupRouter = router; },
    buildSelectedGroup: (selection, clean) => runBuildResult(selection, clean, false),
    buildExact: (selection, clean, token) => runBuildResult(selection, clean, false, token),
    loadPrepared: async (request, options) => {
      if (!trusted() || !preparedCurrent(request)) { await options.retainedLease?.release().catch(() => undefined); return null; }
      try { store.beginTargetTransition(options.recover ? 'Recovering captured pair' : 'Loading captured pair', request.workflowOwner); }
      catch (error) { await options.retainedLease?.release().catch(() => undefined); throw error; }
      try {
        return await runLoad({ selection: request.selection, selectionPath: request.selectionPath, receiptPath: request.receiptPath,
          serial: request.serial, core: request.selection.core }, options.recover, options.retainedLease, request);
      } finally { store.endTargetTransition(); }
    },
    debugPrepared: async (request, core, options) => {
      if (!trusted() || !preparedCurrent(request)) { await options.retainedLease?.release().catch(() => undefined); return false; }
      try { store.beginTargetTransition(`Attaching R8-${core.slice(-1)}`, request.workflowOwner); }
      catch (error) { await options.retainedLease?.release().catch(() => undefined); throw error; }
      try {
        return await debugProvider.startManagedAttach(request.receiptPath, core, request.selection, request.serial,
          options.retainedLease, request, () => preparedCurrent(request));
      } finally { store.endTargetTransition(); }
    },
    disposeAsync,
    dispose: () => {
      void disposeAsync().catch((error: Error) => {
        vscode.window.showErrorMessage(`Firmware session cleanup failed: ${error.message}`);
      });
    },
  };
  return controller;
}

