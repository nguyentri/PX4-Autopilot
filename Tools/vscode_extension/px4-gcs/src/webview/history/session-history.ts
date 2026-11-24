// Webview mirror of the host's plot and track history. The host store keeps
// 10 minutes at 10 Hz; the Plots or Track tab asks for it once per page
// (the page is rebuilt when the panel reopens), then live values are appended
// here with the same decimation and cap. No DOM access (loaded by the tests).
import {
  HISTORY_MIN_SPACING_S, HISTORY_RATE_HZ, HISTORY_SECONDS, NAMED_VALUE_PREFIX, PLOTTED_KEYS, SampleMessage,
} from '../../dashboard/dashboard-messages';

export const HISTORY_CAPACITY = HISTORY_SECONDS * HISTORY_RATE_HZ;
/** Trim in batches so appending stays amortised O(1). */
const TRIM_SLACK = 200;

export function isPlottedKey(key: string): boolean {
  return (PLOTTED_KEYS as readonly string[]).includes(key) || key.startsWith(NAMED_VALUE_PREFIX);
}

/** Index of the first sample with `ts >= from` (samples are in time order). */
export function firstIndexAtOrAfter(samples: readonly SampleMessage[], from: number): number {
  let lo = 0;
  let hi = samples.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (samples[mid].ts < from) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

export class SessionHistory {
  private readonly series = new Map<string, SampleMessage[]>();
  /** True once the host's history arrived for this page (or a new connection started empty). */
  seeded = false;
  /** Bumped on every change so tabs redraw only when needed. */
  version = 0;

  clear(seeded: boolean): void {
    this.series.clear();
    this.seeded = seeded;
    this.version += 1;
  }

  /** Take the host history; samples appended locally after its newest one are kept. */
  seed(host: Record<string, SampleMessage[]>): void {
    const local = new Map(this.series);
    this.series.clear();
    for (const [key, samples] of Object.entries(host)) {
      if (!isPlottedKey(key)) continue;
      this.series.set(key, samples.slice(-HISTORY_CAPACITY));
    }
    for (const [key, samples] of local) {
      for (const sample of samples) this.append(key, sample);
    }
    this.seeded = true;
    this.version += 1;
  }

  /** Append one live sample; ignored when older than the newest or closer than 1/10 s to it (the host store's rule). */
  append(key: string, sample: SampleMessage): void {
    if (!isPlottedKey(key)) return;
    let samples = this.series.get(key);
    if (!samples) {
      samples = [];
      this.series.set(key, samples);
    }
    const last = samples[samples.length - 1];
    if (last && sample.ts - last.ts < HISTORY_MIN_SPACING_S) return;
    samples.push(sample);
    if (samples.length > HISTORY_CAPACITY + TRIM_SLACK) samples.splice(0, samples.length - HISTORY_CAPACITY);
    this.version += 1;
  }

  get(key: string): readonly SampleMessage[] {
    const samples = this.series.get(key) ?? [];
    return samples.length > HISTORY_CAPACITY ? samples.slice(-HISTORY_CAPACITY) : samples;
  }

  /** Samples of `key` with `ts >= from`. */
  since(key: string, from: number): readonly SampleMessage[] {
    const samples = this.get(key);
    return samples.slice(firstIndexAtOrAfter(samples, from));
  }

  /** Newest sample time over every key, or undefined when nothing is stored. */
  latestTs(): number | undefined {
    let latest: number | undefined;
    for (const samples of this.series.values()) {
      const ts = samples[samples.length - 1]?.ts;
      if (ts !== undefined && (latest === undefined || ts > latest)) latest = ts;
    }
    return latest;
  }

  keys(prefix = ''): string[] {
    return [...this.series.keys()].filter((k) => k.startsWith(prefix)).sort();
  }
}
