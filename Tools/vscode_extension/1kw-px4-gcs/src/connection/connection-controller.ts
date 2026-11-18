// The one connection this window owns: one sidecar process per connection,
// state idle -> connecting -> connected <-> lost -> disconnecting -> idle.
// No `vscode` import: the tests drive it in plain Node with the real sidecar.
import { BridgeClient, BridgeCommandError, exitError } from '../bridge/bridge-client';
import { BridgeProcess, bridgeSpawnPlan } from '../bridge/bridge-process';
import { BridgeEvent, ConnectArgs, HelloData, LinkData, PROTOCOL_VERSION } from '../bridge/bridge-protocol';
import { VehicleStateStore } from '../vehicle/vehicle-state-store';

export type ConnectionState = 'idle' | 'connecting' | 'connected' | 'lost' | 'disconnecting';

const HELLO_TIMEOUT_MS = 10000;
/** Reply margin on top of the probe time the sidecar spends listening. */
const CONNECT_MARGIN_MS = 10000;

export interface ControllerOptions {
  pythonDir: string;
  log(line: string): void;
  store: VehicleStateStore;
}

/** Decides the `connect` arguments once the sidecar runs (it lists the ports); undefined aborts. */
export type ConnectPlanner = (client: BridgeClient) => Promise<ConnectArgs | undefined>;

type Listener<T> = (value: T) => void;

/** Upper bound on the `connect` reply: every baud listened at for `probeSeconds`, plus a margin. */
export function connectTimeoutMs(args: ConnectArgs): number {
  const probe = args.probeSeconds ?? (args.transport === 'udp' ? 5 : 2);
  const rounds = args.transport === 'udp' ? 1 : Math.max(1, args.baudCandidates.length);
  return Math.ceil(probe * rounds * 1000) + CONNECT_MARGIN_MS;
}

export class ConnectionController {
  private stateValue: ConnectionState = 'idle';
  private bridge: { client: BridgeClient; process: BridgeProcess } | undefined;
  private connectRequest: number | undefined;
  private cancelled = false;
  private readonly stateListeners = new Set<Listener<ConnectionState>>();
  private readonly exitListeners = new Set<Listener<BridgeCommandError>>();
  private readonly eventListeners = new Set<Listener<BridgeEvent>>();
  hello: HelloData | undefined;
  link: LinkData | undefined;

  constructor(private readonly options: ControllerOptions) {}

  get state(): ConnectionState {
    return this.stateValue;
  }

  get client(): BridgeClient | undefined {
    return this.stateValue === 'connected' || this.stateValue === 'lost' ? this.bridge?.client : undefined;
  }

  /** Process id of the running sidecar, if any (tests check it is gone after dispose). */
  get pid(): number | undefined {
    return this.bridge?.process.pid;
  }

  onDidChangeState(listener: Listener<ConnectionState>): { dispose(): void } {
    return subscribe(this.stateListeners, listener);
  }

  /** The sidecar exited while connected (crash or kill): reported once, state is already idle. */
  onDidExitUnexpectedly(listener: Listener<BridgeCommandError>): { dispose(): void } {
    return subscribe(this.exitListeners, listener);
  }

  onEvent(listener: Listener<BridgeEvent>): { dispose(): void } {
    return subscribe(this.eventListeners, listener);
  }

  /**
   * Start a sidecar, check its protocol version, let `plan` choose the
   * arguments and connect. Resolves to the link status, or undefined when the
   * planner or `cancel()` aborted. Rejects with a BridgeCommandError; the
   * sidecar is stopped and the state is idle again on every failure.
   */
  async connect(pythonPath: string, plan: ConnectPlanner): Promise<LinkData | undefined> {
    if (this.stateValue !== 'idle') {
      throw new BridgeCommandError('BAD_ARGUMENT', 'already connected; disconnect first');
    }
    this.cancelled = false;
    this.setState('connecting');
    this.options.store.reset();
    const spawnPlan = bridgeSpawnPlan(pythonPath, this.options.pythonDir);
    const bridge = BridgeClient.start((onLine) => new BridgeProcess(spawnPlan, onLine,
      (line) => this.options.log(`sidecar: ${line}`)), (line) => this.options.log(line));
    this.bridge = bridge;
    bridge.client.onEvent((event) => this.onBridgeEvent(event));
    void bridge.process.exited.then(() => this.onExit(bridge));
    try {
      const hello = await bridge.client.request<HelloData>('hello', undefined, { timeoutMs: HELLO_TIMEOUT_MS });
      if (hello.protocolVersion !== PROTOCOL_VERSION) {
        throw new BridgeCommandError('PROTOCOL_MISMATCH',
          `sidecar speaks protocol ${hello.protocolVersion}, the extension speaks ${PROTOCOL_VERSION}`);
      }
      this.hello = hello;
      const args = this.cancelled ? undefined : await plan(bridge.client);
      if (!args || this.cancelled) {
        await this.stopBridge();
        return undefined;
      }
      const started = bridge.client.start<LinkData>('connect', args as unknown as Record<string, unknown>,
        { timeoutMs: connectTimeoutMs(args) });
      this.connectRequest = started.id;
      const link = await started.reply;
      this.connectRequest = undefined;
      this.link = link;
      this.setState('connected');
      return link;
    } catch (error) {
      this.connectRequest = undefined;
      await this.stopBridge();
      if (error instanceof BridgeCommandError && error.code === 'CANCELLED') return undefined;
      throw error;
    }
  }

  /** Abort a connect in progress (the progress notification's Cancel button). */
  cancel(): void {
    if (this.stateValue !== 'connecting') return;
    this.cancelled = true;
    if (this.connectRequest !== undefined && this.bridge) void this.bridge.client.cancel(this.connectRequest);
  }

  async disconnect(): Promise<void> {
    if (this.stateValue === 'idle' || this.stateValue === 'disconnecting') return;
    if (this.stateValue === 'connecting') {
      this.cancel();
      return;
    }
    this.setState('disconnecting');
    try {
      await this.bridge?.client.request('disconnect', undefined, { timeoutMs: 5000 });
    } catch (error) {
      this.options.log(`disconnect: ${error instanceof Error ? error.message : String(error)}`);
    }
    await this.stopBridge();
  }

  /** Stop the sidecar (deactivate): resolves once the process has exited. */
  async dispose(): Promise<void> {
    await this.stopBridge();
    this.stateListeners.clear();
    this.exitListeners.clear();
    this.eventListeners.clear();
  }

  private async stopBridge(): Promise<void> {
    const bridge = this.bridge;
    if (bridge) {
      if (this.stateValue !== 'idle') this.setState('disconnecting');
      await bridge.process.stop();
    }
    if (this.bridge === bridge) this.toIdle();
  }

  private toIdle(): void {
    this.bridge = undefined;
    this.link = undefined;
    this.setState('idle');
  }

  private onExit(bridge: { client: BridgeClient; process: BridgeProcess }): void {
    if (this.bridge !== bridge) return;
    const unexpected = this.stateValue === 'connected' || this.stateValue === 'lost';
    const exit = bridge.client.exit;
    this.toIdle();
    if (!unexpected || !exit) return;
    const error = exitError(exit);
    for (const listener of [...this.exitListeners]) listener(error);
  }

  private onBridgeEvent(event: BridgeEvent): void {
    this.options.store.ingest(event);
    if (event.name === 'link') {
      const link = event.data as unknown as LinkData;
      this.link = { ...this.link, ...link };
      if (link.state === 'lost' && this.stateValue === 'connected') this.setState('lost');
      else if (link.state === 'connected' && this.stateValue === 'lost') this.setState('connected');
    }
    for (const listener of [...this.eventListeners]) listener(event);
  }

  private setState(state: ConnectionState): void {
    if (this.stateValue === state) return;
    this.stateValue = state;
    for (const listener of [...this.stateListeners]) listener(state);
  }
}

function subscribe<T>(set: Set<T>, listener: T): { dispose(): void } {
  set.add(listener);
  return { dispose: () => set.delete(listener) };
}
