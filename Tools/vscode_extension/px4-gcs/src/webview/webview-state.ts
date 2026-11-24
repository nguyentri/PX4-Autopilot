// Webview-side copy of what the host sent: connection, latest value per key
// with its local arrival time, and an update-rate estimate. Tabs read it on
// animation frames; nothing here touches the DOM.
import {
  CommandOutcomeView, ConsoleState, DashboardConnection, HostMessage, LinkSummary, LogsState, LogTransferView, ModeView,
  ParamOutcomeView, ParamsState, RecordingView, SampleMessage, STALE_AFTER_MS, StatusEntry, WebviewMessage,
} from '../dashboard/dashboard-messages';
import { SessionHistory } from './history/session-history';

const RATE_WINDOW_MS = 5000;

export interface LiveValue {
  sample: SampleMessage;
  /** Local time (ms) the value last changed. */
  at: number;
  /** Local arrival times of distinct samples inside the rate window. */
  arrivals: number[];
}

declare function acquireVsCodeApi(): { postMessage(message: unknown): void };

let api: { postMessage(message: unknown): void } | undefined;

export function postToHost(message: WebviewMessage): void {
  api ??= acquireVsCodeApi();
  api.postMessage(message);
}

type Listener = (message: HostMessage) => void;

export class WebviewState {
  connection: DashboardConnection = 'idle';
  link: LinkSummary | null = null;
  stale = false;
  controlEnabled = true;
  params: ParamsState = { state: 'idle' };
  console: ConsoleState = { state: 'closed' };
  status: StatusEntry[] = [];
  modes: ModeView[] = [];
  commandOutcome: CommandOutcomeView | undefined;
  paramOutcome: ParamOutcomeView | undefined;
  logs: LogsState = { state: 'idle' };
  transfer: LogTransferView | null = null;
  recording: RecordingView = { active: false };
  readonly values = new Map<string, LiveValue>();
  /** Plot and track history (host history plus live values). */
  readonly history = new SessionHistory();
  private readonly listeners = new Set<Listener>();

  constructor(private readonly now: () => number = () => Date.now()) {}

  get connected(): boolean {
    return this.connection === 'connected' || this.connection === 'lost';
  }

  on(listener: Listener): void {
    this.listeners.add(listener);
  }

  apply(message: HostMessage): void {
    switch (message.type) {
      case 'snapshot':
        this.connection = message.connection;
        this.link = message.link;
        this.stale = message.stale;
        this.controlEnabled = message.controlEnabled;
        this.params = message.params;
        this.console = message.console;
        this.status = [...message.status];
        this.modes = message.modes ?? [];
        this.values.clear();
        this.merge(message.values);
        break;
      case 'connection':
        this.connection = message.connection;
        this.link = message.link;
        this.stale = message.stale;
        this.modes = message.modes ?? [];
        if (message.connection === 'connecting') {
          this.history.clear(true);
          this.commandOutcome = undefined;
          this.paramOutcome = undefined;
          this.values.clear();
          this.status = [];
        }
        break;
      case 'values':
        this.stale = message.stale;
        this.merge(message.values);
        break;
      case 'status':
        this.status.push(...message.entries);
        break;
      case 'params':
        this.params = message.params;
        break;
      case 'console':
        this.console = message.console;
        break;
      case 'param_value':
        if (this.params.state === 'done') {
          const entry = message.entry;
          this.params = { ...this.params, params: this.params.params.map((p) => (p.name === entry.name ? entry : p)) };
        }
        break;
      case 'param_result':
        this.paramOutcome = message.outcome;
        break;
      case 'command_result':
        this.commandOutcome = message.outcome;
        break;
      case 'history':
        this.history.seed(message.series);
        break;
      case 'logs':
        this.logs = message.logs;
        break;
      case 'log_transfer':
        this.transfer = message.transfer;
        break;
      case 'recording':
        this.recording = message.recording;
        break;
      default:
        break;
    }
    for (const listener of [...this.listeners]) listener(message);
  }

  /** Mode keys the vehicle reported as available; null when it reported none. */
  availableModes(): string[] | null {
    const modes = this.value<{ reported?: boolean; available?: unknown }>('modes');
    return modes?.reported && Array.isArray(modes.available) ? modes.available.filter((k): k is string => typeof k === 'string')
      : null;
  }

  value<T = Record<string, unknown>>(key: string): T | undefined {
    return this.values.get(key)?.sample.data as T | undefined;
  }

  /** True when the key has no value, or none newer than STALE_AFTER_MS, or the link is lost. */
  isStale(key: string): boolean {
    const live = this.values.get(key);
    return !live || this.stale || this.now() - live.at > STALE_AFTER_MS;
  }

  ageMs(key: string): number | undefined {
    const live = this.values.get(key);
    return live ? this.now() - live.at : undefined;
  }

  /** Distinct samples per second seen over the last five seconds. */
  rateHz(key: string): number {
    const live = this.values.get(key);
    if (!live) return 0;
    const cutoff = this.now() - RATE_WINDOW_MS;
    const recent = live.arrivals.filter((t) => t >= cutoff);
    return recent.length / (RATE_WINDOW_MS / 1000);
  }

  keys(prefix: string): string[] {
    return [...this.values.keys()].filter((k) => k.startsWith(prefix)).sort();
  }

  private merge(values: Record<string, SampleMessage>): void {
    const now = this.now();
    for (const [key, sample] of Object.entries(values)) {
      const live = this.values.get(key);
      if (live && live.sample.ts === sample.ts) continue;
      const arrivals = live ? live.arrivals.filter((t) => t >= now - RATE_WINDOW_MS) : [];
      arrivals.push(now);
      this.values.set(key, { sample, at: now, arrivals });
      this.history.append(key, sample);
    }
  }
}
