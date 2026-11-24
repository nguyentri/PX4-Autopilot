// The vehicle's onboard log list as the Logs tab and the download command see
// it. Three outcomes are kept apart: entries; no answer while the link stayed
// up (PX4 says nothing when it has no logs); and a lost link, whose error is
// shown instead. No `vscode` import.
import { BridgeCommandError } from '../bridge/bridge-client';
import { ConnectionController } from '../connection/connection-controller';
import { LogEntryView, LogsState } from '../dashboard/dashboard-messages';

interface LogListReply {
  entries: LogEntryView[];
  answered: boolean;
  truncated?: boolean;
}

export function logListError(error: unknown): string {
  if (error instanceof BridgeCommandError) {
    if (error.code === 'NOT_CONNECTED') return 'Not connected to a vehicle.';
    if (error.code === 'TIMEOUT') return `No log list: ${error.message}.`;
    return `${error.code}: ${error.message}`;
  }
  return error instanceof Error ? error.message : String(error);
}

const LOST_TEXT = 'The link to the vehicle is lost (no heartbeat), so the log list cannot be read.';

export class LogListStore {
  private current: LogsState = { state: 'idle' };
  private loading: Promise<void> | undefined;
  private readonly subscription: { dispose(): void };

  constructor(private readonly controller: ConnectionController, private readonly onState: (logs: LogsState) => void) {
    // A new connection is a new vehicle (or a rebooted one): the old list no longer applies.
    this.subscription = controller.onDidChangeState((state) => {
      if (state === 'connecting' || state === 'idle') this.set({ state: 'idle' });
    });
  }

  get state(): LogsState {
    return this.current;
  }

  entry(id: number): LogEntryView | undefined {
    return this.current.state === 'done' ? this.current.entries.find((e) => e.id === id) : undefined;
  }

  /** Ask the vehicle for its list; concurrent callers share one request. */
  load(): Promise<void> {
    this.loading ??= this.fetch().finally(() => { this.loading = undefined; });
    return this.loading;
  }

  dispose(): void {
    this.subscription.dispose();
  }

  private async fetch(): Promise<void> {
    const client = this.controller.client;
    if (!client || this.controller.state !== 'connected') {
      this.set({ state: 'error', message: this.controller.state === 'lost' ? LOST_TEXT : 'Not connected to a vehicle.' });
      return;
    }
    this.set({ state: 'loading' });
    try {
      const reply = await client.request<LogListReply>('log_list');
      // Silence means "no logs" only while heartbeats kept coming; a link lost meanwhile explains the silence.
      if (!reply.answered && this.controller.state !== 'connected') {
        this.set({ state: 'error', message: this.controller.state === 'lost' ? LOST_TEXT : 'Not connected to a vehicle.' });
        return;
      }
      this.set({ state: 'done', entries: reply.entries, answered: reply.answered, truncated: reply.truncated === true });
    } catch (error) {
      this.set({ state: 'error', message: logListError(error) });
    }
  }

  private set(state: LogsState): void {
    this.current = state;
    this.onState(state);
  }
}
