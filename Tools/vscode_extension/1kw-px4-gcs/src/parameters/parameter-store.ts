// The vehicle's parameters for the Parameters tab, the edit service and the
// import: runs `param_list`, keeps the last result across a dashboard close,
// applies confirmed writes and decorates each row with the build metadata.
// No `vscode` import.
import { BridgeEvent } from '../bridge/bridge-protocol';
import { ConnectionController } from '../connection/connection-controller';
import { ParamEntry, ParamMetaView, ParamsState } from '../dashboard/dashboard-messages';
import { differsFromDefault } from './parameter-diff';
import { metadataSourceText, ParameterMetadataSet, ParamMeta } from './parameter-metadata';

interface ListReply {
  params: ParamEntry[];
  count: number | null;
  missing: number[];
}

export interface ParameterStoreListener {
  onState(state: ParamsState): void;
  onValue(entry: ParamEntry): void;
}

function metaView(meta: ParamMeta | undefined, type: string): ParamMetaView | undefined {
  if (!meta) return undefined;
  const { name: _name, type: metaType, ...rest } = meta;
  return { ...rest, ...(metaType !== type ? { typeMismatch: metaType } : {}) };
}

export class ParameterStore {
  private stateValue: ParamsState = { state: 'idle' };
  private raw: ParamEntry[] = [];
  private readonly byName = new Map<string, ParamEntry>();
  private metadataSet: ParameterMetadataSet | undefined;
  private requestId: number | undefined;
  private running: Promise<void> | undefined;
  private readonly subscriptions: { dispose(): void }[];

  constructor(private readonly controller: ConnectionController, private readonly listener: ParameterStoreListener) {
    this.subscriptions = [
      controller.onDidChangeState((state) => {
        if (state === 'connecting') this.reset({ state: 'idle' });
        if (state === 'idle' && this.stateValue.state === 'loading') this.set({ state: 'error', message: 'Disconnected.' });
        if (state === 'idle') this.requestId = undefined;
      }),
      controller.onEvent((event) => this.onProgress(event)),
    ];
  }

  get state(): ParamsState {
    return this.stateValue;
  }

  get metadata(): ParameterMetadataSet | undefined {
    return this.metadataSet;
  }

  /** The vehicle's row for a name (decorated), when the list is loaded. */
  entry(name: string): ParamEntry | undefined {
    return this.byName.get(name);
  }

  /** Every visible row of the last complete list. */
  entries(): ParamEntry[] {
    return this.stateValue.state === 'done' ? this.stateValue.params : [];
  }

  meta(name: string): ParamMeta | undefined {
    return this.metadataSet?.byName.get(name);
  }

  /** Replace the metadata (or drop it) and redecorate the list. */
  setMetadata(set: ParameterMetadataSet | undefined): void {
    this.metadataSet = set;
    if (this.stateValue.state === 'done') this.publishList(this.stateValue.count, this.stateValue.missing);
  }

  /** Load once per connection; `force` (Refresh) loads again. A running load is joined. */
  load(force = false): Promise<void> {
    if (this.running) return this.running;
    if (!force && this.stateValue.state === 'done') return Promise.resolve();
    this.running = this.runLoad().finally(() => { this.running = undefined; });
    return this.running;
  }

  /** A write the vehicle confirmed (or the value it holds instead). */
  applyValue(name: string, value: number | null): void {
    const index = this.raw.findIndex((p) => p.name === name);
    if (index < 0) return;
    this.raw[index] = { ...this.raw[index], value };
    const entry = this.decorate(this.raw[index]);
    this.byName.set(name, entry);
    if (this.stateValue.state === 'done') {
      const params = this.stateValue.params.map((p) => (p.name === name ? entry : p));
      this.stateValue = { ...this.stateValue, params };
    }
    this.listener.onValue(entry);
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose();
  }

  private async runLoad(): Promise<void> {
    const client = this.controller.client;
    if (!client) {
      this.set({ state: 'error', message: 'Connect to a vehicle to read its parameters.' });
      return;
    }
    const started = client.start<ListReply>('param_list');
    this.requestId = started.id;
    this.set({ state: 'loading', received: 0, total: null });
    try {
      const reply = await started.reply;
      if (this.requestId !== started.id) return;
      this.raw = reply.params.map((p) => ({ name: p.name, index: p.index, type: p.type, value: p.value }));
      this.publishList(reply.count, reply.missing);
    } catch (error) {
      if (this.requestId !== started.id) return;
      this.set({ state: 'error', message: error instanceof Error ? error.message : String(error) });
    } finally {
      if (this.requestId === started.id) this.requestId = undefined;
    }
  }

  private decorate(entry: ParamEntry): ParamEntry {
    const meta = this.meta(entry.name);
    const differs = differsFromDefault(entry.value, entry.type, meta);
    return { ...entry, meta: metaView(meta, entry.type), ...(differs !== undefined ? { differs } : {}) };
  }

  private publishList(count: number | null, missing: number[]): void {
    const params = this.raw.map((p) => this.decorate(p));
    this.byName.clear();
    for (const p of params) this.byName.set(p.name, p);
    this.set({ state: 'done', params, count, missing, metadata: metadataSourceText(this.metadataSet) });
  }

  private reset(state: ParamsState): void {
    this.raw = [];
    this.byName.clear();
    this.set(state);
  }

  private onProgress(event: BridgeEvent): void {
    if (event.name !== 'param_progress' || this.stateValue.state !== 'loading') return;
    const data = event.data as { id?: number; received?: number; total?: number | null };
    if (data.id !== this.requestId) return;
    this.set({ state: 'loading', received: data.received ?? 0, total: data.total ?? null });
  }

  private set(state: ParamsState): void {
    this.stateValue = state;
    this.listener.onState(state);
  }
}
