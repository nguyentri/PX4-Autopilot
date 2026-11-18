// Starts the Python sidecar under fixed spawn rules and splits its stdout into
// JSON lines. No `vscode` import: the tests load this module in plain Node.
import * as cp from 'child_process';
import * as path from 'path';
import { StringDecoder } from 'string_decoder';

const STDERR_TAIL_LINES = 20;
/** After stdin closes the sidecar disconnects and exits; then SIGTERM, then SIGKILL. */
const TERM_AFTER_MS = 1500;
const KILL_AFTER_MS = 3000;

export interface BridgeExit {
  code: number | null;
  signal: NodeJS.Signals | null;
  /** Set when the interpreter could not be started at all (for example ENOENT). */
  spawnError?: NodeJS.ErrnoException;
  stderrTail: string[];
}

export interface SpawnPlan {
  command: string;
  args: string[];
  options: cp.SpawnOptions;
}

/**
 * Spawn rules: the interpreter from the machine-scoped setting, the packaged
 * `python/` folder as working directory and as the only `PYTHONPATH` entry
 * (an inherited value is dropped so nothing can shadow the package), no shell.
 */
export function bridgeSpawnPlan(pythonPath: string, pythonDir: string, args: string[] = [],
  baseEnv: NodeJS.ProcessEnv = process.env): SpawnPlan {
  const env: NodeJS.ProcessEnv = { ...baseEnv };
  delete env.PYTHONPATH;
  delete env.PYTHONHOME;
  delete env.PYTHONSTARTUP;
  env.PYTHONPATH = path.resolve(pythonDir);
  env.PYTHONDONTWRITEBYTECODE = '1';
  env.PYTHONUNBUFFERED = '1';
  env.PYTHONIOENCODING = 'utf-8';
  return {
    command: pythonPath,
    args: ['-m', 'px4_gcs_bridge', ...args],
    options: { cwd: path.resolve(pythonDir), env, shell: false, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] },
  };
}

/** Collects complete lines from a byte stream. */
export class LineSplitter {
  private readonly decoder = new StringDecoder('utf8');
  private buffer = '';

  constructor(private readonly onLine: (line: string) => void) {}

  push(chunk: Buffer): void {
    this.buffer += this.decoder.write(chunk);
    let index = this.buffer.indexOf('\n');
    while (index >= 0) {
      const line = this.buffer.slice(0, index).replace(/\r$/, '');
      this.buffer = this.buffer.slice(index + 1);
      if (line.trim()) this.onLine(line);
      index = this.buffer.indexOf('\n');
    }
  }
}

export class BridgeProcess {
  readonly child: cp.ChildProcess;
  readonly exited: Promise<BridgeExit>;
  private readonly stderrTail: string[] = [];
  private stopping: Promise<BridgeExit> | undefined;

  constructor(plan: SpawnPlan, onLine: (line: string) => void, onStderr: (line: string) => void) {
    this.child = cp.spawn(plan.command, plan.args, plan.options);
    let spawnError: NodeJS.ErrnoException | undefined;
    this.exited = new Promise((resolve) => {
      this.child.once('error', (error: NodeJS.ErrnoException) => {
        spawnError = error;
        // A failed spawn emits no 'exit'; 'close' still follows on Node >= 16 but resolve here too.
        if (this.child.pid === undefined) resolve({ code: null, signal: null, spawnError, stderrTail: this.stderrTail });
      });
      this.child.once('close', (code, signal) => resolve({ code, signal, spawnError, stderrTail: this.stderrTail }));
    });
    const stdout = new LineSplitter(onLine);
    const stderr = new LineSplitter((line) => {
      this.stderrTail.push(line);
      if (this.stderrTail.length > STDERR_TAIL_LINES) this.stderrTail.shift();
      onStderr(line);
    });
    this.child.stdout?.on('data', (chunk: Buffer) => stdout.push(chunk));
    this.child.stderr?.on('data', (chunk: Buffer) => stderr.push(chunk));
    this.child.stdin?.on('error', () => { /* a dead sidecar is reported through `exited` */ });
  }

  get pid(): number | undefined {
    return this.child.pid;
  }

  get running(): boolean {
    return this.child.pid !== undefined && this.child.exitCode === null && this.child.signalCode === null;
  }

  write(line: string): boolean {
    const stdin = this.child.stdin;
    if (!this.running || !stdin || stdin.destroyed || stdin.writableEnded) return false;
    stdin.write(`${line}\n`);
    return true;
  }

  /** Close stdin (the sidecar then disconnects and exits), escalating to SIGTERM and SIGKILL. */
  stop(): Promise<BridgeExit> {
    if (this.stopping) return this.stopping;
    if (this.running) {
      this.child.stdin?.end();
      const term = setTimeout(() => this.signal('SIGTERM'), TERM_AFTER_MS);
      const kill = setTimeout(() => this.signal('SIGKILL'), KILL_AFTER_MS);
      void this.exited.then(() => { clearTimeout(term); clearTimeout(kill); });
    }
    this.stopping = this.exited;
    return this.stopping;
  }

  private signal(signal: NodeJS.Signals): void {
    if (this.running) this.child.kill(signal);
  }
}

/** One-shot `python -m px4_gcs_bridge doctor`: prints one JSON line and exits. */
export async function runDoctorProcess(pythonPath: string, pythonDir: string,
  timeoutMs = 15000): Promise<{ exit: BridgeExit; line: string | undefined }> {
  let line: string | undefined;
  const bridge = new BridgeProcess(bridgeSpawnPlan(pythonPath, pythonDir, ['doctor']),
    (text) => { line ??= text; }, () => {});
  bridge.child.stdin?.end();
  const timer = setTimeout(() => { void bridge.stop(); }, timeoutMs);
  const exit = await bridge.exited;
  clearTimeout(timer);
  return { exit, line };
}
