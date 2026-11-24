// What the Plots tab can draw: fixed vehicle series plus every NAMED_VALUE_FLOAT
// key seen in the session (the sidecar keeps at most 64). Each series reads one
// number from one history key. No DOM access (loaded by the tests).
import { NAMED_VALUE_PREFIX, SampleMessage } from '../../dashboard/dashboard-messages';
import { firstIndexAtOrAfter } from '../history/session-history';

export interface PlotSeries {
  id: string;
  label: string;
  units: string;
  key: string;
  read(data: Record<string, unknown>): number | null;
}

/** Plot windows in seconds: 30 s, 2 min, 10 min (the full history). */
export const PLOT_WINDOWS = [30, 120, 600] as const;
export const NAMED_VALUE_LIMIT = 64;

function field(name: string, scale = 1): (data: Record<string, unknown>) => number | null {
  return (data) => {
    const value = data[name];
    return typeof value === 'number' && Number.isFinite(value) ? value * scale : null;
  };
}

const RAD_TO_DEG = 180 / Math.PI;

export const FIXED_SERIES: readonly PlotSeries[] = [
  { id: 'roll', label: 'Roll', units: '°', key: 'attitude', read: field('roll', RAD_TO_DEG) },
  { id: 'pitch', label: 'Pitch', units: '°', key: 'attitude', read: field('pitch', RAD_TO_DEG) },
  { id: 'yaw', label: 'Yaw', units: '°', key: 'attitude', read: field('yaw', RAD_TO_DEG) },
  { id: 'altitude', label: 'Altitude (relative)', units: 'm', key: 'position', read: field('relativeAlt') },
  { id: 'climb', label: 'Climb rate', units: 'm/s', key: 'vfr', read: field('climb') },
  { id: 'groundspeed', label: 'Ground speed', units: 'm/s', key: 'vfr', read: field('groundspeed') },
  { id: 'voltage', label: 'Battery voltage', units: 'V', key: 'battery', read: field('voltage') },
  { id: 'current', label: 'Battery current', units: 'A', key: 'battery', read: field('current') },
];

export const DEFAULT_SERIES = ['roll', 'pitch', 'altitude'];

/** Fixed series plus one per named-value key (sorted, capped at 64). */
export function seriesCatalog(namedKeys: readonly string[]): PlotSeries[] {
  const named = namedKeys.filter((k) => k.startsWith(NAMED_VALUE_PREFIX)).sort().slice(0, NAMED_VALUE_LIMIT)
    .map((key): PlotSeries => {
      const name = key.slice(NAMED_VALUE_PREFIX.length);
      return { id: key, label: name, units: '', key, read: field('value') };
    });
  return [...FIXED_SERIES, ...named];
}

/** uPlot data for one series over `[end - windowSeconds, end]`: times and values (gaps as null). */
export function windowData(samples: readonly SampleMessage[], series: PlotSeries, end: number,
  windowSeconds: number): [number[], (number | null)[]] {
  const xs: number[] = [];
  const ys: (number | null)[] = [];
  for (let i = firstIndexAtOrAfter(samples, end - windowSeconds); i < samples.length; i += 1) {
    const sample = samples[i];
    if (sample.ts > end) break;
    xs.push(sample.ts);
    ys.push(series.read(sample.data));
  }
  return [xs, ys];
}
