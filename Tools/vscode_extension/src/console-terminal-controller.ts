import * as cp from 'child_process';
import * as crypto from 'crypto';
import * as fs from 'fs';
import * as net from 'net';
import * as path from 'path';
import * as vscode from 'vscode';
import { BackendClient, ProbeLeaseHandle } from './backend-client';
import { SelectionStore } from './selection-store';
import { ConsoleHandoff, SetupOperationToken } from './types';

interface Session {
  key: string; core: string; transport: string; token: SetupOperationToken;
  selectionPath: string; receiptPath: string; serial: string; uuid: string;
  start: Promise<void>; stopping: boolean; stop?: Promise<void>;
  terminal?: vscode.Terminal; socket?: net.Socket; output?: vscode.EventEmitter<string>;
  lease?: ProbeLeaseHandle; backendStarted?: boolean; pid?: number; processStart?: string;
  python?: string; device?: string;
  preserveLease?: boolean; handoffClaimed?: boolean; pairGeneration?: number; receiptId?: string; pairSha256?: string;
}

function executable(name: string): string | undefined {
  return (name.includes('/') ? [name] : (process.env.PATH || '').split(path.delimiter).map((p) => path.join(p, name)))
    .find((p) => { try { fs.accessSync(p, fs.constants.X_OK); return fs.statSync(p).isFile(); } catch { return false; } });
}
function processStart(pid: number): string | undefined {
  try { return fs.readFileSync(`/proc/${pid}/stat`, 'utf8').split(')').slice(1).join(')').trim().split(/\s+/)[19]; } catch { return undefined; }
}
const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Exact terminal/socket owners. Persisted UART metadata never authorizes signals. */
export class ConsoleTerminalController implements vscode.Disposable {
  private readonly sessions = new Map<string, Session>();
  private readonly changed = new vscode.EventEmitter<void>();
  public readonly onDidChange = this.changed.event;
  private readonly closeListener: vscode.Disposable;
  private closed = false;
  constructor(private readonly client: BackendClient, private readonly store: SelectionStore,
    private readonly debugBusy: () => boolean = () => false) {
    this.closeListener = vscode.window.onDidCloseTerminal((terminal) => {
      const session = [...this.sessions.values()].find((s) => s.terminal === terminal);
      if (session && !session.stopping) { void this.stopSession(session).catch((error) => this.report(error)); }
    });
  }
  private report(error: unknown): void { void vscode.window.showErrorMessage(`Console cleanup needs attention: ${(error as Error).message}`); }
  public hasOwnedSessions(): boolean { return this.sessions.size > 0; }
  public describe(core: string): string | undefined {
    const session = [...this.sessions.values()].find((s) => s.core === core);
    return session && `${session.transport.toUpperCase()} ${session.stopping ? 'stopping / cleanup pending' : session.terminal ? 'open' : 'starting'}`;
  }
  private current(session: Session): void {
    const pair = this.store.getPreparedPair();
    if (this.closed || session.stopping || vscode.workspace.isTrusted === false || !this.store.isSetupTokenCurrent(session.token)
      || (session.transport === 'rtt' && (pair?.generation !== session.pairGeneration || pair?.prepared?.receiptId !== session.receiptId || pair?.prepared?.pairSha256 !== session.pairSha256))) {
      throw new Error('Console start cancelled because its setup, images, core, probe or device changed.');
    }
  }
  public async startCoreConsole(core: string): Promise<boolean> {
    if (this.closed || vscode.workspace.isTrusted === false) { throw new Error('Trust an active workspace before opening a console.'); }
    this.store.assertMutable();
    const selection = this.store.getSelection();
    const transport = this.store.getConsoleTransport(core);
    if (selection.board !== 'rdk-rzv2h' || !['cr8_0', 'cr8_1'].includes(core) || !['rtt', 'sci4'].includes(transport)) {
      throw new Error('This core/transport has no managed console. Use the documented manual route.');
    }
    if (transport === 'sci4' && (!this.store.getActiveSetup() || core !== 'cr8_0')) { throw new Error('Managed SCI4 requires the saved R8-0 SCI4 setup.'); }
    const key = `${this.store.getActiveSetup()?.id || selection.id}:${core}:${transport}`;
    const existing = this.sessions.get(key);
    if (existing) { if (existing.stopping) { throw new Error('Console cleanup is pending. Stop Sessions before reopening.'); } existing.terminal?.show(); return true; }
    if (transport === 'rtt' && (this.debugBusy() || [...this.sessions.values()].some((s) => s.transport === 'rtt'))) {
      throw new Error('Stop the owned RTT/debug session before starting another probe console.');
    }
    const pair = this.store.getPreparedPair();
    const receiptPath = this.store.getReceiptPath(selection) || '';
    if (transport === 'rtt' && (!receiptPath || (selection.group && (!pair?.prepared || pair.pending || pair.validationError || Object.keys(pair.sourceChanges || {}).length)))) {
      throw new Error('Validate and load the captured images before opening RTT.');
    }
    const session: Session = { key, core, transport, token: this.store.captureSetupToken(core), uuid: crypto.randomUUID(),
      serial: this.store.getSelectedProbe(), selectionPath: this.store.writeSelectionSnapshot(selection), receiptPath,
      pairGeneration: pair?.generation, receiptId: pair?.prepared?.receiptId, pairSha256: pair?.prepared?.pairSha256,
      start: Promise.resolve(), stopping: false };
    this.sessions.set(key, session); this.changed.fire();
    session.start = transport === 'sci4' ? this.startSerial(session) : this.startRtt(session);
    try { await session.start; this.current(session); this.changed.fire(); return true; }
    catch (error) { await this.stopSession(session).catch((cleanup) => this.report(cleanup)); throw error; }
  }
  private async startSerial(session: Session): Promise<void> {
    if (process.platform !== 'linux') { throw new Error('Managed SCI4 currently requires the Linux workspace host (including a WSL host with an attached UART).'); }
    const configured = this.store.getConsoleDevice(session.core);
    if (!path.isAbsolute(configured) || /[\x00-\x1f\x7f]/.test(configured)) { throw new Error('Choose an absolute serial-device path on the workspace extension host.'); }
    const device = fs.realpathSync(configured); const info = fs.statSync(device);
    if (!info.isCharacterDevice()) { throw new Error('SCI4 requires a character device on the workspace host.'); }
    fs.accessSync(device, fs.constants.R_OK | fs.constants.W_OK);
    if (!executable('picocom')) { throw new Error('picocom is missing on the workspace extension host. Install picocom there, then reopen SCI4.'); }
    const root = this.client.getWorkspaceRoot();
    const config = vscode.workspace.getConfiguration('px4Nuttx', vscode.Uri.file(root));
    const python = config.get<string>('pythonPath', 'python3');
    if (!executable(python)) { throw new Error(`Configured Python is unavailable on the workspace host: ${python}`); }
    this.current(session); session.python = python; session.device = device;
    session.terminal = vscode.window.createTerminal({ name: `${this.store.getActiveSetup()?.name || 'Firmware'} · ${session.core} SCI4`,
      shellPath: python, shellArgs: ['-m', 'firmware_workspace.serial_console', '--device', device, '--baud', '115200', '--session-id', session.uuid],
      cwd: root, env: { PYTHONPATH: `${path.join(root, 'Tools')}${path.delimiter}${process.env.PYTHONPATH || ''}` }, isTransient: true });
    session.terminal.show();
    const pid = await session.terminal.processId;
    if (!pid) { throw new Error('SCI4 terminal did not expose its supervisor PID; close the terminal and inspect UART ownership.'); }
    // Only the direct, observed supervisor of this in-memory launch is signalable.
    for (let attempt = 0; attempt < 50; attempt++) {
      try {
        const args = fs.readFileSync(`/proc/${pid}/cmdline`, 'utf8').split('\0');
        if (args.includes(session.uuid) && args.includes('firmware_workspace.serial_console')) {
          session.pid = pid; session.processStart = processStart(pid); break;
        }
      } catch { /* It may already have exited with a prerequisite/busy diagnostic. */ }
      if (session.terminal.exitStatus) { break; }
      await delay(20);
    }
    if (!session.pid || !session.processStart) { throw new Error('SCI4 supervisor ownership could not be observed; inspect the terminal diagnostic (UART_BUSY means another session owns this UART).'); }
    const directory = path.join(process.env.FIRMWARE_WORKSPACE_RUNTIME || `/tmp/px4-firmware-${process.getuid!()}`, 'uart');
    let acknowledged = false;
    for (let attempt = 0; attempt < 150; attempt++) {
      this.current(session);
      if (processStart(session.pid) !== session.processStart) { break; }
      try {
        acknowledged = fs.readdirSync(directory).filter((name) => name.endsWith('.json')).some((name) => {
          const meta = JSON.parse(fs.readFileSync(path.join(directory, name), 'utf8'));
          return meta.sessionId === session.uuid && meta.pid === session.pid && meta.start === session.processStart
            && meta.device === device && meta.childStart && processStart(meta.childPid) === meta.childStart;
        });
      } catch { /* The supervisor publishes metadata only after obtaining flock. */ }
      if (acknowledged) { break; } await delay(20);
    }
    if (!acknowledged) { throw new Error('SCI4 did not acquire its UART/start the client. Inspect the terminal for UART_BUSY or prerequisite diagnostics.'); }
    this.current(session);
  }
  private async reconcile(session: Session): Promise<void> {
    if (!session.serial) { return; }
    try {
      const result = await this.client.runDoctor(undefined, { serial: session.serial });
      if (!result.data?.targetHistory) { throw new Error('Target recovery state is unknown.'); }
      const history = result.data.targetHistory;
      const ready = history.verifiedPair?.pairSha256 === session.pairSha256
        && history.recoveryRequired === false;
      if (!ready && this.store.isSetupTokenCurrent(session.token) && this.store.getPreparedPair()) {
        await this.store.updatePreparedPair(this.store.getSelection().group!, (pair) => pair && ({ ...pair,
          history: { verified: false, message: 'Recover Both required' } }), session.token);
      }
    } catch {
      if (this.store.isSetupTokenCurrent(session.token) && this.store.getPreparedPair()) {
        await this.store.updatePreparedPair(this.store.getSelection().group!, (pair) => pair && ({ ...pair,
          history: { verified: false, message: 'Recovery state unknown; run Doctor before recovery' }, validationError: 'Console ownership/target state is uncertain. Refresh and diagnose before loading.' }), session.token);
      }
    }
  }
  private async startRtt(session: Session): Promise<void> {
    if (!session.serial) { throw new Error('Select a J-Link probe before opening RTT.'); }
    if (this.store.getSelection().group) {
      const doctor = await this.client.runDoctor(undefined, { serial: session.serial });
      // Doctor also reports build prerequisites; only exact target history gates this console.
      const history = doctor.data?.targetHistory;
      this.current(session);
      if (!history || history.recoveryRequired !== false || history.verifiedPair?.pairSha256 !== session.pairSha256) { throw new Error('Load this exact captured pair before opening RTT; diagnose recovery-required/unknown history first.'); }
    }
    session.lease = await this.client.probeLeases.acquire(session.serial); this.current(session);
    session.backendStarted = true;
    const result = await this.client.consoleAction('start', session.selectionPath, session.receiptPath, session.serial,
      { core: session.core, lease: session.lease.lease });
    if (result.status !== 'ok') { await this.reconcile(session); throw new Error(result.diagnostics.map((d) => d.message).join('; ') || 'RTT startup failed'); }
    this.current(session);
    if (result.data?.endpoint !== '127.0.0.1:19021' || result.data?.running !== true || result.data?.core !== session.core || result.data?.transport !== 'rtt') { throw new Error('Managed RTT returned an unexpected endpoint.'); }
    const output = session.output = new vscode.EventEmitter<string>();
    const socket = session.socket = new net.Socket();
    const title = `${this.store.getActiveSetup()?.name || 'Firmware'} · ${session.core} RTT`;
    const terminal: vscode.Pseudoterminal = {
      onDidWrite: output.event,
      open: () => output.fire(`${title}\r\nReceipt/history binds images; it is not live proof after an external reset or reload.\r\n`),
      close: () => { if (!session.stopping) { void this.stopSession(session).catch((error) => this.report(error)); } },
      handleInput: (data) => { if (!socket.destroyed) { socket.write(data); } },
    };
    // NSH emits bare LF but a pseudoterminal needs CRLF; a CR may end one chunk and its LF start the next.
    let afterCr = false;
    socket.on('data', (data) => {
      const text = data.toString();
      output.fire(text.replace(/\r?\n/g, (eol, offset: number) => (eol === '\n' && !(offset === 0 && afterCr) ? '\r\n' : eol)));
      afterCr = text.endsWith('\r');
    });
    socket.on('close', () => { if (!session.stopping) { void this.stopSession(session).catch((error) => this.report(error)); } });
    socket.on('error', (error) => { output.fire(`\r\nRTT: ${error.message}\r\n`); });
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => { socket.destroy(); reject(new Error('RTT endpoint did not accept the interactive client.')); }, 5000);
      socket.once('connect', () => { clearTimeout(timeout); resolve(); });
      socket.once('error', (error) => { clearTimeout(timeout); reject(error); });
      socket.connect(19021, '127.0.0.1');
    });
    this.current(session); session.terminal = vscode.window.createTerminal({ name: title, pty: terminal, isTransient: true }); session.terminal.show();
  }
  private stopSession(session: Session, preserveLease = false): Promise<void> {
    if (session.stop) { return session.stop; }
    session.stopping = true; session.preserveLease = preserveLease; this.changed.fire();
    session.stop = session.start.catch(() => undefined).then(async () => {
      session.socket?.destroy(); session.terminal?.dispose();
      if (session.transport === 'sci4') {
        if (session.pid && session.processStart && processStart(session.pid) === session.processStart) {
          process.kill(session.pid, 'SIGTERM');
          for (let attempt = 0; attempt < 150 && processStart(session.pid) === session.processStart; attempt++) { await delay(20); }
          if (processStart(session.pid) === session.processStart) { throw new Error('SCI4 supervisor did not exit; its UART remains busy. Inspect the exact terminal before retrying.'); }
        } else if (session.terminal && !session.pid && session.terminal.exitStatus === undefined) {
          throw new Error('SCI4 supervisor identity is uncertain. Inspect the terminal/UART owner before reopening; persisted metadata cannot authorize signalling.');
        }
        if (session.device && session.python) {
          const root = this.client.getWorkspaceRoot();
          await new Promise<void>((resolve, reject) => {
            cp.execFile(session.python!, ['-m', 'firmware_workspace.serial_console', '--device', session.device!, '--baud', '115200', '--session-id', session.uuid, '--check'],
              { cwd: root, env: { ...process.env, PYTHONPATH: `${path.join(root, 'Tools')}${path.delimiter}${process.env.PYTHONPATH || ''}` }, timeout: 5000 },
              (error) => error ? reject(new Error('UART kernel lease remains busy or could not be verified. Inspect its existing owner; no unobserved process was signalled.')) : resolve());
          });
        }
      } else if (session.backendStarted && session.lease) {
        const result = await this.client.consoleAction('stop', session.selectionPath, session.receiptPath, session.serial,
          { core: session.core, lease: session.lease.lease });
        if (result.status !== 'ok') { await this.reconcile(session); throw new Error('RTT backend did not acknowledge teardown; probe reservation retained.'); }
        session.backendStarted = false;
      }
      if (!preserveLease) { await session.lease?.release(); }
      session.output?.dispose(); this.sessions.delete(session.key); this.changed.fire();
    });
    // A failed stop retains the owner and is retryable only through explicit Stop.
    void session.stop.catch(() => { session.stop = undefined; });
    return session.stop;
  }
  public async stopRttForDebugHandoff(): Promise<ConsoleHandoff> {
    const session = [...this.sessions.values()].find((s) => s.transport === 'rtt');
    if (!session) { return { ok: true }; }
    try { await this.stopSession(session, true); const lease = session.preserveLease && !session.handoffClaimed ? session.lease : undefined; session.handoffClaimed = true; return { ok: true, lease }; }
    catch (error) { this.report(error); return { ok: false }; }
  }
  public async stopOwnedSessions(): Promise<void> {
    const results = await Promise.allSettled([...this.sessions.values()].map((s) => this.stopSession(s)));
    const failures = results.filter((result): result is PromiseRejectedResult => result.status === 'rejected');
    if (failures.length) { throw new Error(failures.map((r) => String(r.reason)).join('; ')); }
  }
  public async disposeAsync(): Promise<void> { this.closed = true; await this.stopOwnedSessions(); this.closeListener.dispose(); this.changed.dispose(); }
  public dispose(): void { void this.disposeAsync().catch((error) => this.report(error)); }
}
