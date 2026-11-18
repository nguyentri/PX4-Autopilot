// Maps dashboard webview requests to the connection controller and sidecar,
// and forwards vehicle state to the page at most 20 Hz (the store's rate).
// It outlives the panel: the status log and parameter list survive a close.
// No `vscode` import: commands, the modal and the clipboard are injected.
import { ConnectionController } from '../connection/connection-controller';
import { ConsoleSession } from '../console/console-session';
import { Confirmation } from '../control/confirmation-text';
import { GuardedCommandService } from '../control/guarded-command-service';
import { LogDownloadHost, LogDownloadService } from '../logs/log-download-service';
import { LogListStore } from '../logs/log-list-store';
import { ParameterEditService } from '../parameters/parameter-edit-service';
import { ParameterStore } from '../parameters/parameter-store';
import { SessionJournal } from '../session/session-journal';
import { VehicleStateStore } from '../vehicle/vehicle-state-store';
import {
  HostMessage, InspectorRow, LinkSummary, ModeView, NAMED_VALUE_PREFIX, PLOTTED_KEYS, RecordingView, RunnableCommand,
  SampleMessage, TAB_IDS, TabId, WebviewMessage,
} from './dashboard-messages';
import { StatusLogBuffer } from './status-log-buffer';
import { StreamDemand, StreamNeed } from './stream-demand';

/** Streams the Sensor Bench raises while visible (MAVLink message id, interval in microseconds). */
export const TAB_STREAMS: Partial<Record<TabId, StreamNeed[]>> = {
  sensors: [
    { message: 105, intervalUs: 100000 }, // HIGHRES_IMU 10 Hz
    { message: 29, intervalUs: 200000 }, // SCALED_PRESSURE 5 Hz
    { message: 132, intervalUs: 200000 }, // DISTANCE_SENSOR 5 Hz
  ],
};

/** Events that have their own message instead of the generic value forward. */
const NOT_VALUES = new Set(['statustext', 'shell_data', 'inspector', 'param_progress', 'log_progress', 'recording']);

export interface DashboardRouterOptions {
  controller: ConnectionController;
  store: VehicleStateStore;
  journal: SessionJournal;
  /** The NSH console warning (its own accept button). */
  confirm(message: string): Promise<boolean>;
  /** Guarded-action modal: Cancel is the default; true only for the confirm button. */
  confirmAction(confirmation: Confirmation): Promise<boolean>;
  controlEnabled(): boolean;
  runCommand(command: RunnableCommand): void;
  /** Save dialog, free space and the finish notice for log downloads. */
  logHost: LogDownloadHost;
  /** The recorder's current state (the router only shows it). */
  recording(): RecordingView;
  copy(text: string): void;
  log(line: string): void;
}

export class DashboardRouter {
  readonly console: ConsoleSession;
  readonly params: ParameterStore;
  readonly commands: GuardedCommandService;
  readonly editor: ParameterEditService;
  readonly streams: StreamDemand;
  readonly logs: LogListStore;
  readonly downloads: LogDownloadService;
  private readonly status = new StatusLogBuffer();
  private readonly subscriptions: { dispose(): void }[];
  private post: ((message: HostMessage) => void) | undefined;
  private visible = false;
  private tab: TabId = 'fly';
  private inspecting = false;
  /** Demand changes run one after another, so a fast tab switch cannot interleave requests. */
  private demandChain: Promise<void> = Promise.resolve();

  constructor(private readonly options: DashboardRouterOptions) {
    const { controller, store } = options;
    this.console = new ConsoleSession({
      controller, journal: options.journal, confirm: options.confirm, controlEnabled: options.controlEnabled,
      log: options.log, onState: (state) => this.send({ type: 'console', console: state }),
      onOutput: (text) => this.send({ type: 'shell', text }),
    });
    this.params = new ParameterStore(controller, {
      onState: (params) => this.send({ type: 'params', params }),
      onValue: (entry) => this.send({ type: 'param_value', entry }),
    });
    const vehicle = { controller, store, controlEnabled: options.controlEnabled };
    this.commands = new GuardedCommandService({ ...vehicle, journal: options.journal, confirm: options.confirmAction });
    this.editor = new ParameterEditService({ ...vehicle, params: this.params, journal: options.journal,
      confirm: options.confirmAction });
    this.logs = new LogListStore(controller, (logs) => this.send({ type: 'logs', logs }));
    this.downloads = new LogDownloadService({ controller, journal: options.journal, host: options.logHost,
      onTransfer: (transfer) => this.send({ type: 'log_transfer', transfer }) });
    this.streams = new StreamDemand({
      request: async (message, intervalUs) => { await controller.client?.request('stream_request', { message, intervalUs }); },
      release: async (message) => { await controller.client?.request('stream_release', { message }); },
    }, (note) => {
      if (!(TAB_IDS as readonly string[]).includes(note.owner)) return;
      this.send({ type: 'stream_note', tab: note.owner as TabId, message: note.message, outcome: note.outcome,
        reason: note.reason });
    });
    this.subscriptions = [
      store.onDidChange((keys) => this.forwardValues(keys)),
      controller.onDidChangeState((state) => {
        if (state === 'connecting' || state === 'idle') {
          this.streams.reset();
          this.inspecting = false;
        }
        if (state === 'connecting') this.status.clear();
        if (state === 'connected') void this.applyDemand();
        this.send({ type: 'connection', connection: state, link: this.linkSummary(), stale: store.stale,
          modes: this.modeViews() });
      }),
      controller.onEvent((event) => {
        if (event.name === 'statustext') {
          this.send({ type: 'status', entries: [this.status.add(event.ts, event.data)] });
        } else if (event.name === 'inspector' && this.tab === 'inspector') {
          const data = event.data as { messages?: InspectorRow[]; unknown?: number };
          this.send({ type: 'inspector', messages: data.messages ?? [], unknown: data.unknown ?? 0 });
        }
      }),
    ];
  }

  /** A panel is showing the dashboard; `post` delivers to its webview. */
  attach(post: (message: HostMessage) => void): void {
    this.post = post;
  }

  /** The panel closed: stop the shell and give back every raised stream. */
  async detach(): Promise<void> {
    this.post = undefined;
    await this.setVisible(false);
    await this.console.close();
  }

  async setVisible(visible: boolean): Promise<void> {
    if (this.visible === visible) return;
    this.visible = visible;
    if (visible) this.sendSnapshot();
    await this.applyDemand();
  }

  async handle(message: WebviewMessage): Promise<void> {
    switch (message.type) {
      case 'ready':
        this.sendSnapshot();
        return;
      case 'run':
        this.options.runCommand(message.command);
        return;
      case 'tab':
        await this.selectTab(message.tab);
        return;
      case 'params_refresh':
        await this.params.load(true);
        return;
      case 'command':
        this.send({ type: 'command_result', outcome: await this.commands.run(message.action, message.mode) });
        return;
      case 'param_edit':
        this.send({ type: 'param_result', outcome: await this.editor.edit(message.name, message.value) });
        return;
      case 'console_open':
        await this.console.open();
        return;
      case 'console_input':
        await this.console.write(message.data);
        return;
      case 'console_close':
        await this.console.close();
        return;
      case 'copy':
        this.options.copy(message.text);
        return;
      case 'history_request':
        this.sendHistory();
        return;
      case 'logs_refresh':
        await this.logs.load();
        return;
      case 'log_download': {
        const entry = this.logs.entry(message.id);
        if (entry) await this.downloads.download(entry);
        return;
      }
      case 'log_cancel':
        await this.downloads.cancel();
        return;
    }
  }

  async selectTab(tab: TabId): Promise<void> {
    if (!(TAB_IDS as readonly string[]).includes(tab)) return;
    const left = this.tab;
    this.tab = tab;
    if (left === 'console' && tab !== 'console') await this.console.close();
    if (tab === 'parameters' && this.options.controller.client) void this.params.load(false);
    if (tab === 'logs' && this.options.controller.state === 'connected' && this.logs.state.state === 'idle') void this.logs.load();
    await this.applyDemand();
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose();
    this.console.dispose();
    this.params.dispose();
    this.logs.dispose();
  }

  /** The recorder changed state (start, stop, disconnect). */
  recordingChanged(recording: RecordingView): void {
    this.send({ type: 'recording', recording });
  }

  /** Raise the current tab's streams while visible; release everything else. */
  private applyDemand(): Promise<void> {
    this.demandChain = this.demandChain.then(() => this.updateDemand(), () => this.updateDemand());
    return this.demandChain;
  }

  private async updateDemand(): Promise<void> {
    const client = this.options.controller.client;
    const active = this.visible && client !== undefined;
    for (const [tab, needs] of Object.entries(TAB_STREAMS)) {
      if (active && tab === this.tab) await this.streams.acquire(tab, needs ?? []);
      else await this.streams.releaseOwner(tab);
    }
    const inspect = active && this.tab === 'inspector';
    if (inspect === this.inspecting || !client) return;
    this.inspecting = inspect;
    try {
      await client.request(inspect ? 'inspector_subscribe' : 'inspector_unsubscribe');
    } catch (error) {
      this.options.log(`inspector: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  private forwardValues(keys: ReadonlySet<string>): void {
    if (!this.post || !this.visible) return;
    const all = this.options.store.snapshot();
    const values: Record<string, SampleMessage> = {};
    for (const [key, sample] of Object.entries(all)) {
      if ((keys.has('*') || keys.has(key)) && !NOT_VALUES.has(key)) values[key] = sample;
    }
    this.send({ type: 'values', values, stale: this.options.store.stale });
  }

  private sendSnapshot(): void {
    const { controller, store } = this.options;
    const values: Record<string, SampleMessage> = {};
    for (const [key, sample] of Object.entries(store.snapshot())) if (!NOT_VALUES.has(key)) values[key] = sample;
    this.send({
      type: 'snapshot', connection: controller.state, link: this.linkSummary(), stale: store.stale, values,
      status: this.status.entries(), params: this.params.state, console: this.console.state,
      controlEnabled: this.options.controlEnabled(), tab: this.tab, modes: this.modeViews(),
    });
    this.send({ type: 'logs', logs: this.logs.state });
    this.send({ type: 'log_transfer', transfer: this.downloads.transfer });
    this.send({ type: 'recording', recording: this.options.recording() });
  }

  /** The store's 10-minute history for the keys the Plots and Track tabs use. */
  private sendHistory(): void {
    const { store } = this.options;
    const series: Record<string, SampleMessage[]> = {};
    for (const key of store.historyKeys()) {
      if ((PLOTTED_KEYS as readonly string[]).includes(key) || key.startsWith(NAMED_VALUE_PREFIX)) series[key] = store.series(key);
    }
    this.send({ type: 'history', series });
  }

  private modeViews(): ModeView[] {
    return this.commands.modes().map(({ key, name, needsSticks }) => ({ key, name, needsSticks }));
  }

  private linkSummary(): LinkSummary | null {
    const link = this.options.controller.link;
    if (!link) return null;
    return { transport: link.transport, port: link.port, baud: link.baud, host: link.host, udpPort: link.udpPort,
      systemId: link.systemId };
  }

  private send(message: HostMessage): void {
    this.post?.(message);
  }
}
