// Request/reply correlation and typed events over one BridgeProcess. Short
// commands time out on a fixed limit; long commands (PROGRESS_EVENT) time out
// after 5 s without a progress event and are then cancelled in the sidecar.
// No `vscode` import: the tests load this module in plain Node.
import { BridgeExit, BridgeProcess } from './bridge-process';
import {
  BridgeErrorBody, BridgeEvent, BridgeReply, CommandName, ErrorCode, HostErrorCode, PROGRESS_EVENT,
} from './bridge-protocol';

export const SHORT_TIMEOUT_MS = 15000;
export const PROGRESS_TIMEOUT_MS = 5000;

export class BridgeCommandError extends Error {
  constructor(readonly code: ErrorCode | HostErrorCode, message: string,
    readonly details: Record<string, unknown> = {}) {
    super(message);
    this.name = 'BridgeCommandError';
  }

  static fromBody(body: BridgeErrorBody | undefined): BridgeCommandError {
    return new BridgeCommandError(body?.code ?? 'INTERNAL', body?.message ?? 'malformed error reply', body?.details ?? {});
  }
}

/** The error every pending and later request rejects with once the sidecar is gone. */
export function exitError(exit: BridgeExit): BridgeCommandError {
  return exit.spawnError
    ? new BridgeCommandError('SPAWN_FAILED', exit.spawnError.message, { errno: exit.spawnError.code })
    : new BridgeCommandError('BRIDGE_EXITED', `sidecar exited (code ${exit.code}, signal ${exit.signal})`,
      { code: exit.code, signal: exit.signal, stderr: exit.stderrTail.slice(-5) });
}

export interface RequestOptions {
  /** Fixed reply limit for short commands (default 15 s). */
  timeoutMs?: number;
  /** Inactivity limit for long commands (default 5 s). */
  progressTimeoutMs?: number;
}

export interface StartedRequest<T> {
  id: number;
  reply: Promise<T>;
}

interface Pending {
  cmd: CommandName;
  resolve(data: Record<string, unknown>): void;
  reject(error: BridgeCommandError): void;
  timer: NodeJS.Timeout | undefined;
  arm(): void;
}

type EventListener = (event: BridgeEvent) => void;

export class BridgeClient {
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private readonly listeners = new Set<EventListener>();
  private exitInfo: BridgeExit | undefined;

  /** Use `BridgeClient.start` so the line handler exists before the first output line. */
  private constructor(private readonly log: (line: string) => void) {}

  static start(spawn: (onLine: (line: string) => void) => BridgeProcess,
    log: (line: string) => void): { client: BridgeClient; process: BridgeProcess } {
    const client = new BridgeClient(log);
    const process = spawn((line) => client.onLine(line));
    client.attach(process);
    return { client, process };
  }

  private process!: BridgeProcess;

  private attach(process: BridgeProcess): void {
    this.process = process;
    void process.exited.then((exit) => {
      this.exitInfo = exit;
      const reason = exitError(exit);
      for (const [id, entry] of this.pending) {
        clearTimeout(entry.timer);
        this.pending.delete(id);
        entry.reject(reason);
      }
    });
  }

  get exit(): BridgeExit | undefined {
    return this.exitInfo;
  }

  onEvent(listener: EventListener): { dispose(): void } {
    this.listeners.add(listener);
    return { dispose: () => this.listeners.delete(listener) };
  }

  request<T = Record<string, unknown>>(cmd: CommandName, args?: Record<string, unknown>,
    options: RequestOptions = {}): Promise<T> {
    return this.start<T>(cmd, args, options).reply;
  }

  start<T = Record<string, unknown>>(cmd: CommandName, args?: Record<string, unknown>,
    options: RequestOptions = {}): StartedRequest<T> {
    const id = this.nextId++;
    const reply = new Promise<T>((resolve, reject) => {
      if (this.exitInfo || !this.process.running) {
        // A failed spawn (ENOENT) has no pid yet: report the spawn error, not a generic exit.
        void this.process.exited.then((exit) => reject(exitError(exit)));
        return;
      }
      const long = PROGRESS_EVENT[cmd] !== undefined;
      const limit = long ? options.progressTimeoutMs ?? PROGRESS_TIMEOUT_MS : options.timeoutMs ?? SHORT_TIMEOUT_MS;
      const entry: Pending = {
        cmd,
        resolve: (data) => resolve(data as T),
        reject,
        timer: undefined,
        arm: () => {
          clearTimeout(entry.timer);
          entry.timer = setTimeout(() => this.expire(id, long, limit), limit);
        },
      };
      this.pending.set(id, entry);
      entry.arm();
      const command = args === undefined ? { id, cmd } : { id, cmd, args };
      if (!this.process.write(JSON.stringify(command))) {
        this.pending.delete(id);
        clearTimeout(entry.timer);
        void this.process.exited.then((exit) => reject(exitError(exit)));
      }
    });
    return { id, reply };
  }

  /** Ask the sidecar to cancel a running command; resolves to whether it was still running. */
  async cancel(id: number): Promise<boolean> {
    if (!this.pending.has(id)) return false;
    try {
      const data = await this.request<{ cancelled: boolean }>('cancel', { target: id }, { timeoutMs: 3000 });
      return data.cancelled;
    } catch {
      return false;
    }
  }

  private expire(id: number, long: boolean, limit: number): void {
    const entry = this.pending.get(id);
    if (!entry) return;
    this.pending.delete(id);
    const seconds = (limit / 1000).toFixed(0);
    if (long) {
      // The reply to the cancelled command arrives later and is dropped as an orphan.
      void this.request('cancel', { target: id }, { timeoutMs: 3000 }).catch(() => undefined);
      entry.reject(new BridgeCommandError('TIMEOUT', `${entry.cmd}: no progress for ${seconds} s; cancelled`));
    } else {
      entry.reject(new BridgeCommandError('TIMEOUT', `${entry.cmd}: no reply within ${seconds} s`));
    }
  }

  private onLine(line: string): void {
    let message: BridgeReply | BridgeEvent;
    try {
      message = JSON.parse(line);
    } catch {
      this.log(`sidecar wrote a non-JSON line: ${line.slice(0, 200)}`);
      return;
    }
    if (message.type === 'event') {
      this.progress(message);
      for (const listener of [...this.listeners]) listener(message);
      return;
    }
    if (message.type !== 'reply') return;
    const entry = message.id === null ? undefined : this.pending.get(message.id);
    if (!entry) return;
    this.pending.delete(message.id as number);
    clearTimeout(entry.timer);
    if (message.ok) entry.resolve(message.data ?? {});
    else entry.reject(BridgeCommandError.fromBody(message.error));
  }

  private progress(event: BridgeEvent): void {
    const id = (event.data as { id?: unknown }).id;
    if (typeof id !== 'number') return;
    const entry = this.pending.get(id);
    if (entry && PROGRESS_EVENT[entry.cmd] === event.name) entry.arm();
  }
}
