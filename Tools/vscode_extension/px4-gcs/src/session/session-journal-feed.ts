// Feeds the session journal and statistics from the controller: connections
// (vehicle and transport), link state changes, flight mode and arming changes
// from heartbeats, and every STATUSTEXT. Telemetry goes to the statistics,
// not the journal. No `vscode` import.
import { ConnectionController } from '../connection/connection-controller';
import { SessionJournal } from './session-journal';
import { SessionStatistics } from './session-statistics';

const STAT_EVENTS = new Set(['position', 'local_position', 'vfr', 'battery']);

export class SessionJournalFeed {
  readonly statistics = new SessionStatistics();
  /** First connection of this window session (the report's start). */
  started: string | undefined;
  private linkState: string | undefined;
  private mode: string | undefined;
  private armed: boolean | undefined;
  private readonly subscriptions: { dispose(): void }[];

  constructor(controller: ConnectionController, private readonly journal: SessionJournal,
    private readonly now: () => Date = () => new Date()) {
    this.subscriptions = [
      controller.onDidChangeState((state) => {
        if (state === 'connected') {
          const link = controller.link;
          this.started ??= this.now().toISOString();
          this.journal.append('connection', { state, systemId: link?.systemId ?? null,
            transport: link?.transport ?? null, port: link?.port ?? null, baud: link?.baud ?? null,
            host: link?.host ?? null, udpPort: link?.udpPort ?? null });
        } else if (state === 'idle') {
          this.journal.append('connection', { state });
          this.mode = this.armed = this.linkState = undefined;
        }
      }),
      controller.onEvent((event) => {
        const data = event.data as Record<string, unknown>;
        if (STAT_EVENTS.has(event.name)) {
          this.statistics.add(event.name, data, new Date(event.ts * 1000).toISOString());
        } else if (event.name === 'heartbeat') {
          this.heartbeat(data);
        } else if (event.name === 'statustext') {
          this.journal.append('statustext', { severity: data.severity, text: String(data.text ?? ''),
            partial: data.partial === true });
        } else if (event.name === 'link' && typeof data.state === 'string' && data.state !== this.linkState) {
          this.linkState = data.state;
          this.journal.append('link', { state: data.state });
        }
      }),
    ];
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose();
  }

  private heartbeat(data: Record<string, unknown>): void {
    const mode = typeof data.mode === 'string' ? data.mode : undefined;
    if (mode !== undefined && mode !== this.mode) {
      this.journal.append('mode', { mode, from: this.mode ?? null });
      this.mode = mode;
    }
    if (typeof data.armed === 'boolean' && data.armed !== this.armed) {
      if (this.armed !== undefined || data.armed) this.journal.append('arming', { armed: data.armed });
      this.armed = data.armed;
    }
  }
}
