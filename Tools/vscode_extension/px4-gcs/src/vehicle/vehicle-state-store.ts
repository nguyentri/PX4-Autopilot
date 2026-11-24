// Latest value per sidecar event plus bounded history for plots and the track.
// History keeps 10 minutes decimated to 10 Hz on insert; change notifications
// are coalesced to at most 20 Hz. No `vscode` import (loaded by the tests).
import { BridgeEvent, EventName, HeartbeatData, LinkData } from '../bridge/bridge-protocol';
import { HISTORY_MIN_SPACING_S, HISTORY_RATE_HZ, HISTORY_SECONDS } from '../dashboard/dashboard-messages';

export { HISTORY_RATE_HZ, HISTORY_SECONDS };
export const NOTIFY_RATE_HZ = 20;
const HISTORY_CAPACITY = HISTORY_SECONDS * HISTORY_RATE_HZ;

/** Events whose values are kept as history (sensors and named values per sub-key). */
const HISTORY_EVENTS: ReadonlySet<EventName> = new Set<EventName>([
  'attitude', 'position', 'local_position', 'gps', 'battery', 'vfr', 'sensors', 'named_value',
]);

export interface Sample {
  ts: number;
  data: Record<string, unknown>;
}

/** Fixed-capacity ring buffer, oldest sample overwritten first. */
export class RingBuffer<T> {
  private readonly items: (T | undefined)[];
  private start = 0;
  private size = 0;

  constructor(readonly capacity: number) {
    this.items = new Array<T | undefined>(capacity);
  }

  get length(): number {
    return this.size;
  }

  push(item: T): void {
    const index = (this.start + this.size) % this.capacity;
    this.items[index] = item;
    if (this.size < this.capacity) this.size += 1;
    else this.start = (this.start + 1) % this.capacity;
  }

  last(): T | undefined {
    return this.size === 0 ? undefined : this.items[(this.start + this.size - 1) % this.capacity];
  }

  toArray(): T[] {
    const out: T[] = [];
    for (let i = 0; i < this.size; i += 1) out.push(this.items[(this.start + i) % this.capacity] as T);
    return out;
  }

  clear(): void {
    this.start = 0;
    this.size = 0;
    this.items.fill(undefined);
  }
}

/** History key: event name, plus `:kind` for sensors and `:name` for named values. */
export function historyKey(event: BridgeEvent): string {
  const data = event.data as { kind?: unknown; name?: unknown };
  if (event.name === 'sensors' && typeof data.kind === 'string') return `sensors:${data.kind}`;
  if (event.name === 'named_value' && typeof data.name === 'string') return `named_value:${data.name}`;
  return event.name;
}

type ChangeListener = (keys: ReadonlySet<string>) => void;

export class VehicleStateStore {
  private readonly latest = new Map<string, Sample>();
  private readonly history = new Map<string, RingBuffer<Sample>>();
  private readonly listeners = new Set<ChangeListener>();
  private changed = new Set<string>();
  private flushTimer: NodeJS.Timeout | undefined;
  private lastFlush = 0;
  /** True while the link is lost: values are shown greyed, nothing is cleared. */
  stale = false;

  onDidChange(listener: ChangeListener): { dispose(): void } {
    this.listeners.add(listener);
    return { dispose: () => this.listeners.delete(listener) };
  }

  get link(): LinkData | undefined {
    return this.latest.get('link')?.data as LinkData | undefined;
  }

  get heartbeat(): HeartbeatData | undefined {
    return this.latest.get('heartbeat')?.data as HeartbeatData | undefined;
  }

  get<T = Record<string, unknown>>(key: string): T | undefined {
    return this.latest.get(key)?.data as T | undefined;
  }

  /** Latest sample of one key, with its sidecar timestamp. */
  latestSample(key: string): Sample | undefined {
    return this.latest.get(key);
  }

  /** Latest sample of every key (dashboard replay on open). */
  snapshot(): Record<string, Sample> {
    return Object.fromEntries(this.latest);
  }

  /** Keys that have history (the sensors and named values per sub-key). */
  historyKeys(): string[] {
    return [...this.history.keys()];
  }

  series(key: string): Sample[] {
    return this.history.get(key)?.toArray() ?? [];
  }

  ingest(event: BridgeEvent): void {
    const key = historyKey(event);
    const sample = { ts: event.ts, data: event.data };
    this.latest.set(key, sample);
    if (event.name === 'link') {
      const state = (event.data as unknown as LinkData).state;
      this.stale = state === 'lost';
    } else if (event.name === 'heartbeat') {
      this.stale = false;
    }
    if (HISTORY_EVENTS.has(event.name)) this.record(key, sample);
    this.markChanged(key);
  }

  /** Forget everything (new connection). */
  reset(): void {
    this.latest.clear();
    this.history.clear();
    this.stale = false;
    this.markChanged('*');
  }

  dispose(): void {
    clearTimeout(this.flushTimer);
    this.listeners.clear();
  }

  private record(key: string, sample: Sample): void {
    let ring = this.history.get(key);
    if (!ring) {
      ring = new RingBuffer<Sample>(HISTORY_CAPACITY);
      this.history.set(key, ring);
    }
    const previous = ring.last();
    if (previous && sample.ts - previous.ts < HISTORY_MIN_SPACING_S) return;
    ring.push(sample);
  }

  private markChanged(key: string): void {
    this.changed.add(key);
    if (this.flushTimer) return;
    const wait = Math.max(0, this.lastFlush + 1000 / NOTIFY_RATE_HZ - Date.now());
    this.flushTimer = setTimeout(() => this.flush(), wait);
  }

  private flush(): void {
    this.flushTimer = undefined;
    this.lastFlush = Date.now();
    const keys = this.changed;
    this.changed = new Set();
    for (const listener of [...this.listeners]) listener(keys);
  }
}
