import * as crypto from 'crypto';
import * as vscode from 'vscode';
import { BackendClient, ProbeLeaseHandle, WorkspaceTrustError } from './backend-client';
import { SelectionStore } from './selection-store';
import { ConsoleHandoff, FirmwareSelection } from './types';

const DEBUG_TEARDOWN_TIMEOUT_MS = 15000;

interface ManagedDebugLease {
  lease: ProbeLeaseHandle;
  session: vscode.DebugSession;
}

interface PendingDebugLease {
  lease: ProbeLeaseHandle;
  core: string;
}

interface TerminationWaiter {
  resolve: (managed: ManagedDebugLease) => void;
  reject: (error: Error) => void;
  timeout: NodeJS.Timeout;
}

export class Px4NuttxDebugProvider implements vscode.DebugConfigurationProvider, vscode.Disposable {
  private readonly pendingLeases = new Map<string, PendingDebugLease>();
  private readonly activeLeases = new Map<string, ManagedDebugLease>();
  private readonly terminationWaiters = new Map<string, TerminationWaiter>();
  private stopConsoleForHandoff: (() => Promise<ConsoleHandoff>) | undefined;

  constructor(
    private readonly client: BackendClient,
    private readonly store: SelectionStore
  ) {}

  /** Attach lifecycle listeners to the exact managed VS Code session. */
  public registerLifecycle(context: vscode.ExtensionContext): void {
    const debugApi = vscode.debug as typeof vscode.debug & {
      onDidStartDebugSession?: (listener: (session: vscode.DebugSession) => void) => vscode.Disposable;
      onDidTerminateDebugSession?: (listener: (session: vscode.DebugSession) => void) => vscode.Disposable;
    };
    if (debugApi.onDidStartDebugSession) {
      context.subscriptions.push(debugApi.onDidStartDebugSession((session) => this.onSessionStarted(session)));
    }
    if (debugApi.onDidTerminateDebugSession) {
      context.subscriptions.push(debugApi.onDidTerminateDebugSession((session) => this.onSessionTerminated(session)));
    }
  }

  public setConsoleHandoff(handler: (() => Promise<ConsoleHandoff>) | undefined): void {
    this.stopConsoleForHandoff = handler;
  }

  /**
   * Resolve only managed configurations. Manual launch.json entries pass
   * through untouched and do not reserve a probe or invoke the backend.
   */
  resolveDebugConfiguration(
    _folder: vscode.WorkspaceFolder | undefined,
    config: vscode.DebugConfiguration,
    _token?: vscode.CancellationToken
  ): vscode.ProviderResult<vscode.DebugConfiguration> {
    if (!config || !config.px4NuttxManaged) {
      return config;
    }
    if (vscode.workspace?.isTrusted === false) {
      void vscode.window.showErrorMessage('Managed debugging requires workspace trust.');
      return undefined;
    }
    return config;
  }

  public async startManagedAttach(
    receiptPath: string,
    targetCore?: string,
    selectionOverride?: FirmwareSelection,
    probeSerial?: string,
    retainedLease?: ProbeLeaseHandle
  ): Promise<boolean> {
    if (vscode.workspace?.isTrusted === false) {
      await retainedLease?.release().catch(() => undefined);
      vscode.window.showErrorMessage('Managed debugging requires workspace trust.');
      return false;
    }

    const selection = selectionOverride || this.store.getSelection();
    const boundReceipt = this.store.getReceiptPath(selection);
    if (!boundReceipt || boundReceipt !== receiptPath) {
      await retainedLease?.release().catch(() => undefined);
      vscode.window.showErrorMessage('The selected artifact does not match the active firmware profile. Build the selected profile again.');
      return false;
    }

    // Freeze the probe/core before any asynchronous console handoff. A later
    // profile or probe selection must not redirect this operation.
    const serial = probeSerial || this.store.getSelectedProbe();
    const core = targetCore || this.store.getSelectedCore();
    if (!serial) {
      await retainedLease?.release().catch(() => undefined);
      vscode.window.showErrorMessage('Select a J-Link probe before attaching the debugger.');
      return false;
    }

    let handoffLease: ProbeLeaseHandle | undefined = retainedLease;
    if (!handoffLease && this.stopConsoleForHandoff) {
      const handoff = await this.stopConsoleForHandoff();
      if (!handoff.ok) {
        vscode.window.showErrorMessage('Debugging is waiting for the owned console to stop cleanly.');
        return false;
      }
      handoffLease = handoff.lease;
    }
    const lease = handoffLease || await this.client.probeLeases.acquire(serial).catch((error: Error) => {
      vscode.window.showErrorMessage(`Unable to reserve probe ${serial}: ${error.message}`);
      return null;
    });
    if (!lease) {
      return false;
    }
    if (lease.lease.serial !== serial) {
      await lease.release().catch(() => undefined);
      vscode.window.showErrorMessage('The retained probe reservation does not match the selected serial.');
      return false;
    }

    const releaseLease = async (): Promise<void> => {
      try {
        await lease.release();
      } catch (error) {
        vscode.window.showWarningMessage(`Probe reservation cleanup is still pending: ${(error as Error).message}`);
      }
    };

    let leaseId: string | undefined;
    try {
      const selectionSnapshot = this.store.writeSelectionSnapshot(selection);
      const configuration = vscode.Uri?.file
        ? vscode.workspace.getConfiguration('px4Nuttx', vscode.Uri.file(this.store.getWorkspaceRoot()))
        : vscode.workspace.getConfiguration('px4Nuttx');
      const gdbPath = configuration.get<string>('gdbPath', '');
      const res = await this.client.getDebugConfig(
        selectionSnapshot,
        receiptPath,
        serial,
        core,
        { lease: lease.lease, gdb: gdbPath || undefined }
      );
      if (res.status !== 'ok' || !res.data?.configuration) {
        const errs = res.diagnostics.map((diagnostic) => diagnostic.message).join('; ');
        await releaseLease();
        vscode.window.showErrorMessage(`Failed generating debug configuration: ${errs || 'operation was blocked'}`);
        return false;
      }

      leaseId = crypto.randomUUID();
      const debugConfig: vscode.DebugConfiguration = {
        ...res.data.configuration,
        px4NuttxManaged: true,
        px4NuttxLeaseId: leaseId,
        px4NuttxWorkspaceRoot: this.store.getWorkspaceRoot(),
        px4NuttxCore: core,
      };

      this.pendingLeases.set(leaseId, { lease, core });
      const folder = this.getWorkspaceFolder();
      if (!folder) {
        this.pendingLeases.delete(leaseId);
        await lease.release().catch(() => undefined);
        vscode.window.showErrorMessage('The firmware workspace folder is no longer open; debugger attach was cancelled.');
        return false;
      }
      const started = await vscode.debug.startDebugging(folder, debugConfig);
      if (!started) {
        this.pendingLeases.delete(leaseId);
        lease.sendEvent?.({ event: 'debug-failed', core });
        await releaseLease();
        vscode.window.showErrorMessage('Debugger did not start; the probe reservation was released.');
        return false;
      }
      // The lease is transferred to the exact session once VS Code emits its
      // start event. Keeping this pending entry covers the startup gap.
      return true;
    } catch (error) {
      if (leaseId) {
        this.pendingLeases.delete(leaseId);
        lease?.sendEvent?.({ event: 'debug-failed', core });
      }
      await releaseLease();
      const message = error instanceof WorkspaceTrustError ? error.message : (error as Error).message;
      vscode.window.showErrorMessage(`Failed starting managed debugger: ${message}`);
      return false;
    }
  }

  private getWorkspaceFolder(): vscode.WorkspaceFolder | undefined {
    const folders = vscode.workspace.workspaceFolders || [];
    return folders.find((folder) => folder.uri.fsPath === this.store.getWorkspaceRoot());
  }

  private onSessionStarted(session: vscode.DebugSession): void {
    const leaseId = session.configuration?.px4NuttxLeaseId as string | undefined;
    if (!leaseId) {
      return;
    }
    const pending = this.pendingLeases.get(leaseId);
    if (!pending) {
      return;
    }
    this.pendingLeases.delete(leaseId);
    this.activeLeases.set(session.id, { lease: pending.lease, session });
  }

  private onSessionTerminated(session: vscode.DebugSession): void {
    const managed = this.activeLeases.get(session.id);
    if (managed) {
      this.activeLeases.delete(session.id);
      const waiter = this.terminationWaiters.get(session.id);
      if (waiter) {
        this.terminationWaiters.delete(session.id);
        clearTimeout(waiter.timeout);
        waiter.resolve(managed);
        return;
      }
      void managed.lease.release().catch((error: Error) => {
        this.activeLeases.set(session.id, managed);
        vscode.window.showErrorMessage(`Probe reservation cleanup failed after debug termination: ${error.message}`);
      });
      return;
    }

    // Cortex-Debug can report termination before its start event when the
    // adapter fails during startup. Release the pending reservation and tell
    // the supervisor that target state may be indeterminate.
    const leaseId = session.configuration?.px4NuttxLeaseId as string | undefined;
    if (!leaseId) {
      return;
    }
    const pending = this.pendingLeases.get(leaseId);
    if (!pending) {
      return;
    }
    this.pendingLeases.delete(leaseId);
    const failedCore = session.configuration?.px4NuttxCore as string | undefined;
    pending.lease.sendEvent?.({ event: 'debug-failed', core: failedCore || pending.core });
    void pending.lease.release().catch((error: Error) => {
      vscode.window.showErrorMessage(`Probe reservation cleanup failed after debugger startup failure: ${error.message}`);
    });
  }

  private waitForTermination(sessionId: string): Promise<ManagedDebugLease> {
    const existing = this.terminationWaiters.get(sessionId);
    if (existing) {
      return Promise.reject(new Error(`Termination is already being awaited for owned debug session ${sessionId}.`));
    }
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.terminationWaiters.delete(sessionId);
        reject(new Error(`Owned debug session ${sessionId} did not acknowledge termination.`));
      }, DEBUG_TEARDOWN_TIMEOUT_MS);
      timeout.unref?.();
      this.terminationWaiters.set(sessionId, { resolve, reject, timeout });
    });
  }

  private cancelTerminationWait(sessionId: string): void {
    const waiter = this.terminationWaiters.get(sessionId);
    if (!waiter) {
      return;
    }
    this.terminationWaiters.delete(sessionId);
    clearTimeout(waiter.timeout);
  }

  /** Stop only this provider's sessions before releasing their probe leases. */
  public async disposeAsync(): Promise<void> {
    const active = Array.from(this.activeLeases.entries());
    for (const [sessionId, managed] of active) {
      if (!this.activeLeases.has(sessionId)) {
        continue;
      }
      const terminated = this.waitForTermination(sessionId);
      let stopError: Error | undefined;
      try {
        const stopped = await vscode.debug.stopDebugging(managed.session) as unknown as boolean | void;
        if (stopped === false && this.activeLeases.has(sessionId)) {
          stopError = new Error(`Owned debug session ${sessionId} refused termination.`);
        }
      } catch (error) {
        if (this.activeLeases.has(sessionId)) {
          stopError = error as Error;
        }
      }
      if (stopError) {
        this.cancelTerminationWait(sessionId);
        throw stopError;
      }

      let ended: ManagedDebugLease;
      try {
        ended = await terminated;
      } catch (error) {
        throw error;
      }
      try {
        await ended.lease.release();
      } catch (error) {
        this.activeLeases.set(sessionId, ended);
        throw error;
      }
    }

    const pending = Array.from(this.pendingLeases.entries());
    for (const [leaseId, pendingLease] of pending) {
      this.pendingLeases.delete(leaseId);
      pendingLease.lease.sendEvent?.({ event: 'debug-failed', core: pendingLease.core });
      try {
        await pendingLease.lease.release();
      } catch (error) {
        this.pendingLeases.set(leaseId, pendingLease);
        throw error;
      }
    }
  }

  public dispose(): void {
    void this.disposeAsync().catch((error: Error) => {
      vscode.window.showErrorMessage(`Managed debug cleanup failed: ${error.message}`);
    });
  }
}

