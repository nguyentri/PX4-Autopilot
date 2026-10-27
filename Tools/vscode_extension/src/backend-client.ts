import * as cp from 'child_process';
import * as path from 'path';
import * as vscode from 'vscode';
import {
  CatalogData,
  DoctorData,
  FirmwareOperation,
  OperationOptions,
  OperationResult,
  ProbeLease,
  ImportImagesData,
  LoadProgressEvent,
} from './types';

// Python reaps its own process group with a three-second TERM grace. Let it
// finish before escalating the owning backend, or its children can outlive it.
const CHILD_TERM_GRACE_MS = 10000;
const PROBE_START_TIMEOUT_MS = 15000;
const PROBE_RELEASE_TIMEOUT_MS = 30000;

export function parseProgressLine(line: string, operationId?: string): LoadProgressEvent | undefined {
  if (!line.startsWith('PX4_WORKSPACE_EVENT ') || !operationId) { return undefined; }
  try {
    const value = JSON.parse(line.slice('PX4_WORKSPACE_EVENT '.length));
    if (value.eventVersion === 1 && value.operationInstanceId === operationId
      && ['cr8_0', 'cr8_1'].includes(value.core) && ['load', 'verify'].includes(value.phase)
      && ['begin', 'ok', 'fail', 'indeterminate'].includes(value.state) && typeof value.logPath === 'string') { return value; }
  } catch { /* Unknown records remain ordinary stderr diagnostics. */ }
  return undefined;
}

export class WorkspaceTrustError extends Error {
  public readonly code = 'WORKSPACE_TRUST_REQUIRED';

  constructor(operation: string) {
    super(`Workspace trust is required before running the ${operation} operation.`);
    this.name = 'WorkspaceTrustError';
  }
}

function workspaceIsTrusted(): boolean {
  return vscode.workspace?.isTrusted !== false;
}

function terminateChild(child: cp.ChildProcess): void {
  if (child.exitCode !== null || child.killed) {
    return;
  }

  try {
    if (process.platform !== 'win32' && child.pid) {
      process.kill(-child.pid, 'SIGTERM');
    } else {
      child.kill('SIGTERM');
    }
  } catch {
    try {
      child.kill('SIGTERM');
    } catch {
      // The process may have exited between the state check and the signal.
    }
  }
}

function forceTerminateChild(child: cp.ChildProcess): void {
  if (child.exitCode !== null || child.signalCode !== null) {
    return;
  }

  try {
    if (process.platform !== 'win32' && child.pid) {
      process.kill(-child.pid, 'SIGKILL');
    } else {
      child.kill('SIGKILL');
    }
  } catch {
    try {
      child.kill('SIGKILL');
    } catch {
      // The process may have exited between the state check and the signal.
    }
  }
}

function terminateChildWithEscalation(child: cp.ChildProcess): NodeJS.Timeout | undefined {
  terminateChild(child);
  if (child.exitCode !== null || child.signalCode !== null) {
    return undefined;
  }
  const timeout = setTimeout(() => forceTerminateChild(child), CHILD_TERM_GRACE_MS);
  timeout.unref?.();
  return timeout;
}

function pythonEnvironment(workspaceRoot: string, extraEnvironment: NodeJS.ProcessEnv = {}): NodeJS.ProcessEnv {
  return {
    ...process.env,
    ...extraEnvironment,
    PYTHONPATH: `${path.join(workspaceRoot, 'Tools')}:${process.env.PYTHONPATH || ''}`,
  };
}

export interface ProbeLeaseHandle {
  readonly lease: ProbeLease;
  release(): Promise<void>;
  sendEvent?(event: { event: string; core?: string }): void;
}

/**
 * A long-lived backend reservation. The backend owns the actual probe and
 * console cleanup; closing stdin is the only release path used by the
 * extension so unrelated J-Link processes are never terminated.
 */
export class ProbeSession implements ProbeLeaseHandle {
  private released = false;
  private closed = false;
  private releasePromise: Promise<void> | null = null;

  constructor(
    private readonly child: cp.ChildProcess,
    public readonly lease: ProbeLease
  ) {
    this.child.once('close', () => {
      this.closed = true;
      this.released = true;
    });
  }

  public release(): Promise<void> {
    if (this.releasePromise) {
      return this.releasePromise;
    }

    this.released = true;
    if (this.child.exitCode !== null || this.child.signalCode !== null) {
      this.releasePromise = this.child.exitCode === 0
        ? Promise.resolve()
        : Promise.reject(new Error('Probe supervisor exited without acknowledging clean teardown.'));
      return this.releasePromise;
    }
    this.releasePromise = new Promise<void>((resolve, reject) => {
      let settled = false;
      let timeout: NodeJS.Timeout | undefined;
      const finish = (code: number | null): void => {
        if (settled) {
          return;
        }
        settled = true;
        if (timeout) {
          clearTimeout(timeout);
        }
        if (code === 0) {
          resolve();
        } else {
          reject(new Error('Probe supervisor failed during owned process teardown.'));
        }
      };
      const fail = (error: Error): void => {
        if (settled) {
          return;
        }
        settled = true;
        if (timeout) {
          clearTimeout(timeout);
        }
        reject(error);
      };

      this.child.once('close', finish);
      try {
        this.child.stdin?.end();
      } catch {
        terminateChildWithEscalation(this.child);
      }

      timeout = setTimeout(() => {
        if (!settled) {
          forceTerminateChild(this.child);
          fail(new Error('Probe reservation did not acknowledge release before the cleanup timeout.'));
        }
      }, PROBE_RELEASE_TIMEOUT_MS);
      timeout.unref?.();
    });
    return this.releasePromise;
  }

  public isReleased(): boolean {
    return this.closed;
  }

  public sendEvent(event: { event: string; core?: string }): void {
    if (this.released || !this.child.stdin?.writable) {
      return;
    }
    try {
      this.child.stdin.write(`${JSON.stringify(event)}\n`);
    } catch {
      // The supervisor may have exited; release will perform the bounded cleanup.
    }
  }
}

/** Share one reservation between the console and one managed debug session. */
export class ProbeLeaseManager implements vscode.Disposable {
  private readonly sessions = new Map<string, ProbeSession>();
  private readonly pending = new Set<string>();

  constructor(private readonly client: BackendClient) {}

  public async acquire(serial: string): Promise<ProbeLeaseHandle> {
    const existing = this.sessions.get(serial);
    if (existing) {
      if (!existing.isReleased()) {
        throw new Error(`Probe ${serial} is already reserved by another target operation.`);
      }
      this.sessions.delete(serial);
    }
    if (this.pending.has(serial)) {
      throw new Error(`Probe ${serial} is already starting another target operation.`);
    }

    this.pending.add(serial);
    try {
      const session = await this.client.startProbeSession(serial);
      this.sessions.set(serial, session);
      return this.createHandle(serial, session);
    } finally {
      this.pending.delete(serial);
    }
  }

  private createHandle(serial: string, session: ProbeSession): ProbeLeaseHandle {
    let releasePromise: Promise<void> | undefined;
    return {
      lease: session.lease,
      sendEvent: (event) => session.sendEvent(event),
      release: (): Promise<void> => {
        if (!releasePromise) {
          releasePromise = (async () => {
            if (this.sessions.get(serial) !== session) { return; }
            await session.release();
            if (this.sessions.get(serial) === session) { this.sessions.delete(serial); }
          })();
        }
        return releasePromise;
      },
    };
  }

  public dispose(): void {
    for (const session of this.sessions.values()) {
      void session.release().catch(() => {
        // Deactivation cannot surface a rejected cleanup promise to the user.
      });
    }
    this.sessions.clear();
  }
}

export interface BuildOptions extends OperationOptions {
  clean?: boolean;
}

export interface LoadOptions extends OperationOptions {
  recover?: boolean;
  expectReceiptId?: string;
  expectPairSha256?: string;
}

export interface DebugConfigOptions extends OperationOptions {
  gdb?: string | boolean;
  requireLoaded?: boolean;
  expectReceiptId?: string;
  expectPairSha256?: string;
}

export interface DoctorOptions extends OperationOptions { serial?: string }

export interface ConsoleOptions extends OperationOptions {
  core?: string;
}

export class BackendClient {
  public readonly probeLeases: ProbeLeaseManager;
  private readonly ownedChildren = new Set<cp.ChildProcess>();
  private disposed = false;

  constructor(private readonly workspaceRoot: string) {
    this.probeLeases = new ProbeLeaseManager(this);
  }

  public getWorkspaceRoot(): string {
    return this.workspaceRoot;
  }

  private getPythonPath(): string {
    const config = vscode.Uri?.file
      ? vscode.workspace.getConfiguration('px4Nuttx', vscode.Uri.file(this.workspaceRoot))
      : vscode.workspace.getConfiguration('px4Nuttx');
    return config.get<string>('pythonPath', 'python3');
  }

  private getScriptPath(): string {
    return path.join(this.workspaceRoot, 'Tools', 'firmware-workspace.py');
  }

  private assertTrusted(operation: string): void {
    if (!workspaceIsTrusted()) {
      throw new WorkspaceTrustError(operation);
    }
  }

  public async executeCommand<T = any>(
    subcommand: string,
    args: string[] = [],
    options: OperationOptions = {}
  ): Promise<OperationResult<T>> {
    this.assertTrusted(subcommand);
    if (options.cancellationToken?.isCancellationRequested) {
      return {
        protocolVersion: 1,
        operationId: subcommand,
        status: 'cancelled',
        data: {} as T,
        diagnostics: [{ level: 'warning', code: 'CANCELLED', message: `${subcommand} was cancelled before it started.` }],
        childExitCode: 130,
        receiptPath: null,
      };
    }

    const python = this.getPythonPath();
    const script = this.getScriptPath();
    const fullArgs = [script, subcommand, ...args, '--json'];
    const optionEnvironment = options['env'] || {};
    const env = { ...optionEnvironment };
    if (options.operationInstanceId) { env.FIRMWARE_WORKSPACE_OPERATION_ID = options.operationInstanceId; }
    if (options.lease) {
      env.FIRMWARE_PROBE_LEASE = options.lease.leaseToken;
      env.FIRMWARE_PROBE_SERIAL = options.lease.serial;
    }

    return new Promise((resolve, reject) => {
      let stdout = '';
      let stderr = '';
      let progressBuffer = '';
      let settled = false;
      let cancellationSubscription: vscode.Disposable | undefined;
      let cancellationEscalation: NodeJS.Timeout | undefined;

      const child = cp.spawn(python, fullArgs, {
        cwd: this.workspaceRoot,
        env: pythonEnvironment(this.workspaceRoot, env),
        detached: process.platform !== 'win32',
        stdio: ['pipe', 'pipe', 'pipe'],
      });
      this.ownedChildren.add(child);
      let cancellationRequested = false;

      const finishError = (error: Error): void => {
        if (settled) {
          return;
        }
        settled = true;
        cancellationSubscription?.dispose();
        if (cancellationEscalation) {
          clearTimeout(cancellationEscalation);
        }
        this.ownedChildren.delete(child);
        reject(error);
      };

      child.stdout?.on('data', (data: Buffer | string) => {
        const chunk = data.toString();
        stdout += chunk;
        options.onOutput?.(chunk, 'stdout');
      });

      child.stderr?.on('data', (data: Buffer | string) => {
        const chunk = data.toString();
        stderr = (stderr + chunk).slice(-2 * 1024 * 1024);
        options.onOutput?.(chunk, 'stderr');
        progressBuffer += chunk;
        let newline: number;
        while ((newline = progressBuffer.indexOf('\n')) >= 0) {
          const line = progressBuffer.slice(0, newline).trim();
          progressBuffer = progressBuffer.slice(newline + 1);
          const event = parseProgressLine(line, options.operationInstanceId);
          if (event) { options.onProgress?.(event); }
        }
        progressBuffer = progressBuffer.slice(-65536);
      });

      child.once('error', (error) => {
        this.ownedChildren.delete(child);
        finishError(new Error(`Failed to spawn backend CLI (${python}): ${error.message}`));
      });

      cancellationSubscription = options.cancellationToken?.onCancellationRequested(() => {
        cancellationRequested = true;
        if (!cancellationEscalation) {
          cancellationEscalation = terminateChildWithEscalation(child);
        }
      });

      child.once('close', (code) => {
        if (settled) {
          return;
        }
        settled = true;
        cancellationSubscription?.dispose();
        if (cancellationEscalation) {
          clearTimeout(cancellationEscalation);
        }
        this.ownedChildren.delete(child);

        if (!stdout.trim()) {
          if (cancellationRequested || code === 130 || code === 143) {
            resolve({
              protocolVersion: 1,
              operationId: subcommand,
              status: 'cancelled',
              data: {},
              diagnostics: [{ level: 'warning', code: 'CANCELLED', message: `${subcommand} was cancelled.` }],
              childExitCode: code,
              receiptPath: null,
            } as OperationResult<T>);
            return;
          }
          reject(new Error(`Backend returned empty output (exit code ${code}). Stderr: ${stderr}`));
          return;
        }

        try {
          const parsed = JSON.parse(stdout.trim()) as OperationResult<T>;
          if (code === 130 && parsed.status !== 'cancelled') {
            parsed.status = 'cancelled';
          }
          if (parsed.childExitCode === null || parsed.childExitCode === undefined) {
            parsed.childExitCode = code;
          }
          resolve(parsed);
        } catch (error) {
          reject(new Error(`Failed to parse backend JSON: ${(error as Error).message}\nOutput: ${stdout}\nStderr: ${stderr}`));
        }
      });
    });
  }

  public async startProbeSession(serial: string): Promise<ProbeSession> {
    this.assertTrusted('probe reservation');
    if (this.disposed) {
      throw new Error('The firmware workspace client has already been disposed.');
    }
    if (!serial.trim()) {
      throw new Error('Select a J-Link serial before starting a target operation.');
    }

    const child = cp.spawn(this.getPythonPath(), [
      this.getScriptPath(),
      'probe-session',
      '--serial',
      serial,
      '--json',
    ], {
      cwd: this.workspaceRoot,
      env: pythonEnvironment(this.workspaceRoot),
      detached: process.platform !== 'win32',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    // Own the process from spawn until the startup handshake succeeds. This
    // closes the dispose/startup race without touching unrelated processes.
    this.ownedChildren.add(child);
    child.once('close', () => this.ownedChildren.delete(child));

    return new Promise((resolve, reject) => {
      let startupBuffer = '';
      let started = false;
      let stderr = '';
      let settled = false;
      let timeout: NodeJS.Timeout | undefined;

      const fail = (error: Error): void => {
        if (settled) {
          return;
        }
        settled = true;
        if (timeout) {
          clearTimeout(timeout);
        }
        terminateChildWithEscalation(child);
        reject(error);
      };

      child.stderr?.on('data', (data: Buffer | string) => {
        stderr = (stderr + data.toString()).slice(-2 * 1024 * 1024);
      });

      child.stdout?.on('data', (data: Buffer | string) => {
        startupBuffer += data.toString();
        if (started) {
          return;
        }
        const newline = startupBuffer.indexOf('\n');
        if (newline < 0) {
          return;
        }
        const line = startupBuffer.slice(0, newline).trim();
        try {
          const payload = JSON.parse(line) as OperationResult<{ leaseToken?: string; serial?: string }>;
          const leaseToken = payload.data?.leaseToken;
          if (payload.status !== 'ok' || !leaseToken) {
            fail(new Error(payload.diagnostics?.map((d) => d.message).join('; ') || 'Probe reservation was rejected.'));
            return;
          }
          started = true;
          settled = true;
          if (timeout) {
            clearTimeout(timeout);
          }
          // ProbeSession owns the child for the remainder of the lease.
          this.ownedChildren.delete(child);
          resolve(new ProbeSession(child, {
            leaseToken,
            serial: payload.data.serial || serial,
          }));
        } catch (error) {
          fail(new Error(`Invalid probe-session startup JSON: ${(error as Error).message}\nStderr: ${stderr}`));
        }
      });

      child.once('error', (error) => fail(new Error(`Failed to start probe reservation: ${error.message}`)));
      child.once('close', (code) => {
        if (!started && !settled) {
          fail(new Error(`Probe reservation exited before startup (exit code ${code}). Stderr: ${stderr}`));
        }
      });
      timeout = setTimeout(() => {
        fail(new Error(`Probe reservation startup timed out after ${PROBE_START_TIMEOUT_MS / 1000} seconds.`));
      }, PROBE_START_TIMEOUT_MS);
      timeout.unref?.();
    });
  }

  public async getCatalog(): Promise<OperationResult<CatalogData>> {
    return this.executeCommand<CatalogData>('catalog');
  }

  public async importImages(inputPath: string, options: OperationOptions = {}): Promise<OperationResult<ImportImagesData>> {
    return this.executeCommand<ImportImagesData>('import-images', ['--input', inputPath], options);
  }

  public async runDoctor(selectionPath?: string, options: DoctorOptions = {}): Promise<OperationResult<DoctorData>> {
    const args = selectionPath ? ['--selection', selectionPath] : [];
    if (options.serial) { args.push('--serial', options.serial); }
    return this.executeCommand<DoctorData>('doctor', args, options);
  }

  public async resolveSelection(
    selectionPath: string,
    operation: FirmwareOperation = 'build',
    options: OperationOptions = {}
  ): Promise<OperationResult<any>> {
    return this.executeCommand('resolve', ['--selection', selectionPath, '--operation', operation], options);
  }

  public async buildSelection(
    selectionPath: string,
    options: BuildOptions = {}
  ): Promise<OperationResult<any>> {
    const args = ['--selection', selectionPath];
    if (options.clean) {
      args.push('--clean');
    }
    return this.executeCommand('build', args, options);
  }

  public async loadTarget(
    selectionPath: string,
    receiptPath: string,
    serial?: string,
    options: LoadOptions = {}
  ): Promise<OperationResult<any>> {
    const args = ['--selection', selectionPath, '--receipt', receiptPath];
    if (serial) {
      args.push('--serial', serial);
    }
    if (options.recover) {
      args.push('--recover');
    }
    if (options.expectReceiptId) { args.push('--expect-receipt-id', options.expectReceiptId); }
    if (options.expectPairSha256) { args.push('--expect-pair-sha256', options.expectPairSha256); }
    return this.executeCommand('load', args, options);
  }

  public async getDebugConfig(
    selectionPath: string,
    receiptPath: string,
    serial?: string,
    core?: string,
    options: DebugConfigOptions = {}
  ): Promise<OperationResult<any>> {
    const args = ['--selection', selectionPath, '--receipt', receiptPath];
    if (serial) {
      args.push('--serial', serial);
    }
    if (core) {
      args.push('--core', core);
    }
    if (options.requireLoaded) { args.push('--require-loaded'); }
    if (options.expectReceiptId) { args.push('--expect-receipt-id', options.expectReceiptId); }
    if (options.expectPairSha256) { args.push('--expect-pair-sha256', options.expectPairSha256); }
    if (typeof options.gdb === 'string' && options.gdb) {
      args.push('--gdb', options.gdb);
    } else if (options.gdb === true) {
      const config = vscode.Uri?.file
        ? vscode.workspace.getConfiguration('px4Nuttx', vscode.Uri.file(this.workspaceRoot))
        : vscode.workspace.getConfiguration('px4Nuttx');
      args.push('--gdb', config.get<string>('gdbPath', 'gdb-multiarch'));
    }
    return this.executeCommand('debug-config', args, options);
  }

  public async consoleAction(
    action: 'start' | 'stop' | 'status',
    selectionPath: string,
    receiptPath: string,
    serial?: string,
    options: ConsoleOptions = {}
  ): Promise<OperationResult<any>> {
    const args = ['--selection', selectionPath, '--receipt', receiptPath, '--action', action];
    if (serial) {
      args.push('--serial', serial);
    }
    if (options.core) {
      args.push('--core', options.core);
    }
    return this.executeCommand('console', args, options);
  }

  public cancelOperations(): void {
    for (const child of this.ownedChildren) { terminateChildWithEscalation(child); }
  }

  public dispose(): void {
    this.disposed = true;
    for (const child of this.ownedChildren) {
      terminateChildWithEscalation(child);
    }
    this.ownedChildren.clear();
    this.probeLeases.dispose();
  }
}

