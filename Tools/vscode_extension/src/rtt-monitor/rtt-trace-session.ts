import * as vscode from 'vscode';
import { R8Core } from '../types';
import { RttTraceSink } from './rtt-monitor-view-provider';

/** One core over the single-core bridge, or both CR8 consoles over the dual bridge. */
export type TraceTarget = R8Core | 'dual';
export type BridgeStart = { ok: true; endpoints: Partial<Record<R8Core, string>> } | { ok: false; message: string };
export type SerialStart = { ok: true; endpoint: string; stop(): void; onExit(listener: () => void): void } | { ok: false; message: string };

/** What to trace: an RTT target, a serial-console core, or one of each. */
export interface TracePlan { rtt?: TraceTarget; serial?: R8Core }

/** The probe-side and host-side operations the trace session drives. */
export interface TraceBackend {
  /** `owner` is the running workflow's guard, so a resume inside it is admitted. */
  startBridge(target: TraceTarget, owner?: symbol): Promise<BridgeStart>;
  /** Stops the bridge this checkout started; true when one was stopped. */
  stopBridge(): Promise<boolean>;
  /** Relays a core's host UART to a local TCP port; the probe is not involved. */
  startSerial?(core: R8Core): Promise<SerialStart>;
  setupId(): string | undefined;
  /** True while an owned debug session still holds the probe. */
  debugActive(): boolean;
  onSessionChange(listener: () => void): vscode.Disposable;
  recoverBoth(): Promise<unknown>;
}

export function targetCores(target: TraceTarget): R8Core[] {
  return target === 'dual' ? ['cr8_0', 'cr8_1'] : [target];
}

/** CR8-0 when both cores trace over RTT, else the one RTT core, else none. */
export function defaultTraceCore(transport: (core: R8Core) => string): R8Core | undefined {
  return (['cr8_0', 'cr8_1'] as R8Core[]).find((core) => transport(core) === 'rtt');
}

interface Wanted extends TracePlan { setupId?: string }

/**
 * Owns the wish to trace. Probe jobs (load, recover, debug) pause the RTT
 * bridge and resume it on the same target afterwards, unless the user stopped
 * tracing, the setup changed or the job failed. A serial relay never touches
 * the probe, so it keeps streaming through probe jobs (the boot banner after a
 * load shows up live). A failed bridge start is never retried: a failed J-Link
 * connect can reset the board, so the user decides on recovery.
 */
export class RttTraceSession implements vscode.Disposable {
  private wanted?: Wanted;
  private waitingForDebug?: vscode.Disposable;
  private serialRelay?: { core: R8Core; stop(): void };
  /** Bumped by every start and stop, so a superseded start does not continue. */
  private generation = 0;

  constructor(private readonly backend: TraceBackend, private readonly monitor: RttTraceSink) {}

  /** The single RTT core being traced; undefined for dual or serial-only traces. */
  public tracedCore(): R8Core | undefined {
    const rtt = this.wanted?.rtt;
    return rtt && rtt !== 'dual' ? rtt : undefined;
  }

  public tracedPlan(): TracePlan | undefined {
    return this.wanted ? { rtt: this.wanted.rtt, serial: this.wanted.serial } : undefined;
  }

  /** True when every pane the plan wants is attached (or paused around a probe job). */
  public attachedAll(): boolean {
    const wanted = this.wanted;
    if (!wanted || (!wanted.rtt && !wanted.serial)) { return false; }
    const rtt = this.monitor.attachedCores('rtt');
    const serial = this.monitor.attachedCores('serial');
    return (!wanted.rtt || targetCores(wanted.rtt).every((core) => rtt.includes(core)))
      && (!wanted.serial || serial.includes(wanted.serial));
  }

  /** True while both CR8 consoles share one probe session (builds then run at low priority). */
  public dualActive(): boolean { return this.wanted?.rtt === 'dual'; }

  public async start(plan: TracePlan | TraceTarget): Promise<boolean> {
    const next: TracePlan = typeof plan === 'string' ? { rtt: plan } : plan;
    this.cancelDebugWait();
    if (this.monitor.attachedCore()) {
      this.monitor.detach('switching');
      await this.backend.stopBridge();
    }
    if (this.serialRelay && this.serialRelay.core !== next.serial) { this.stopSerial(); }
    const generation = ++this.generation;
    this.wanted = { setupId: this.backend.setupId(), ...next };
    this.monitor.setLayout(next.rtt === 'dual' || (next.rtt && next.serial) ? 'split' : 'single');
    const serialOk = next.serial ? await this.startSerialNow(next.serial) : true;
    if (this.generation !== generation) { return false; }
    const rttOk = next.rtt ? await this.startNow(next.rtt) : true;
    if (serialOk || rttOk) { await this.monitor.reveal(); }
    return serialOk && rttOk;
  }

  /** Moves a single-core RTT trace to another core; a dual trace already shows both. */
  public async switchTo(core: R8Core): Promise<boolean> {
    if (this.wanted?.rtt === 'dual') { return true; }
    if (this.wanted?.rtt === core && this.monitor.attachedCore() === core) { return true; }
    return this.start({ rtt: core, serial: this.wanted?.serial === core ? undefined : this.wanted?.serial });
  }

  /** Stop Sessions and Stop RTT Bridge end the wish to trace, serial relay included. */
  public async stop(): Promise<boolean> {
    this.generation++;
    this.wanted = undefined;
    this.cancelDebugWait();
    const hadSerial = !!this.serialRelay;
    this.stopSerial();
    this.monitor.detach('stopped', undefined, 'all');
    return (await this.backend.stopBridge()) || hadSerial;
  }

  /**
   * Runs a probe job with the RTT bridge paused. `ok` decides whether the job
   * left the target fit to trace; `untilDebugEnds` defers the resume until the
   * owned debug session releases the probe.
   */
  public async pauseFor<T>(label: string, job: () => Promise<T>, ok: (result: T) => boolean, untilDebugEnds = false,
    owner?: symbol): Promise<T> {
    const paused = this.wanted?.rtt && this.monitor.attachedCore() ? this.wanted : undefined;
    if (paused) {
      this.cancelDebugWait();
      this.monitor.detach('paused', label);
      await this.backend.stopBridge();
    }
    let result: T;
    try { result = await job(); }
    catch (error) { if (paused) { this.abandon('the job failed'); } throw error; }
    if (!paused) { return result; }
    if (!ok(result)) { this.abandon(`${label} did not complete`); return result; }
    if (untilDebugEnds && this.backend.debugActive()) {
      this.monitor.detach('paused', `${label} · resumes when the debug session ends`);
      this.waitingForDebug = this.backend.onSessionChange(() => {
        if (this.backend.debugActive()) { return; }
        this.cancelDebugWait();
        void this.resume(paused);
      });
      return result;
    }
    await this.resume(paused, owner);
    return result;
  }

  private async resume(paused: Wanted, owner?: symbol): Promise<void> {
    if (this.wanted !== paused || !paused.rtt) { return; }
    if (paused.setupId !== this.backend.setupId()) { this.abandon('the setup changed'); return; }
    if (await this.startNow(paused.rtt, owner)) { await this.monitor.reveal(); }
  }

  private async startNow(target: TraceTarget, owner?: symbol): Promise<boolean> {
    const result = await this.backend.startBridge(target, owner);
    if (result.ok) {
      const missing = targetCores(target).filter((core) => !result.endpoints[core]);
      for (const core of targetCores(target)) {
        const endpoint = result.endpoints[core];
        if (endpoint) { this.monitor.attach(core, endpoint, 'rtt'); }
      }
      for (const core of missing) { this.monitor.fail(core, 'the bridge reported no port for this core'); }
      return missing.length === 0;
    }
    this.drop('rtt');
    for (const core of targetCores(target)) { this.monitor.fail(core, result.message); }
    void vscode.window.showErrorMessage(`RTT bridge did not start: ${result.message} It is not retried; recover the pair before tracing again.`,
      'Recover Both').then((choice) => { if (choice === 'Recover Both') { void this.backend.recoverBoth(); } });
    return false;
  }

  private async startSerialNow(core: R8Core): Promise<boolean> {
    if (this.serialRelay?.core === core) { return true; }
    if (!this.backend.startSerial) { this.monitor.fail(core, 'serial tracing is unavailable'); return false; }
    const result = await this.backend.startSerial(core);
    if (!result.ok) {
      this.drop('serial');
      this.monitor.fail(core, result.message);
      void vscode.window.showErrorMessage(`Serial console relay did not start: ${result.message}`);
      return false;
    }
    const relay = { core, stop: result.stop };
    this.serialRelay = relay;
    result.onExit(() => {
      if (this.serialRelay !== relay) { return; }
      this.serialRelay = undefined;
      this.drop('serial');
      this.monitor.fail(core, 'the serial relay stopped');
    });
    this.monitor.attach(core, result.endpoint, 'serial');
    return true;
  }

  private stopSerial(): void {
    const relay = this.serialRelay;
    this.serialRelay = undefined;
    relay?.stop();
    if (relay) { this.monitor.detach('stopped', undefined, 'serial'); }
  }

  private abandon(reason: string): void {
    this.drop('rtt');
    this.monitor.detach('stopped', `not resumed: ${reason}`);
  }

  /** Forgets one part of the plan; the whole wish ends when no part is left. */
  private drop(part: 'rtt' | 'serial'): void {
    if (!this.wanted) { return; }
    const next = { ...this.wanted, [part]: undefined };
    this.wanted = next.rtt || next.serial ? next : undefined;
  }

  private cancelDebugWait(): void { this.waitingForDebug?.dispose(); this.waitingForDebug = undefined; }

  public dispose(): void { this.cancelDebugWait(); this.stopSerial(); }
}
