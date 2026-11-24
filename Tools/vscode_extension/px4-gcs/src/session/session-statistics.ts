// Whole-session figures for the report, kept incrementally so they cover the
// full session and not only the store's 10-minute history: the highest
// altitude above home, the fastest ground speed, the lowest battery, and a
// decimated track (LOCAL_POSITION_NED when present, else GPS projected
// equirectangularly around the session's first fix). No `vscode` import.

export interface TrackPoint {
  east: number;
  north: number;
}

export interface Extreme {
  value: number;
  /** ISO time of the sample. */
  time: string;
}

export const TRACK_CAPACITY = 4000;
/** A new track point is kept only this far from the previous one (metres). */
export const TRACK_MIN_STEP_M = 0.5;
const EARTH_RADIUS_M = 6371008.8;
const RAD = Math.PI / 180;

const num = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined;

class DecimatedTrack {
  readonly points: TrackPoint[] = [];

  add(point: TrackPoint): void {
    const last = this.points[this.points.length - 1];
    if (last && Math.hypot(point.east - last.east, point.north - last.north) < TRACK_MIN_STEP_M) return;
    this.points.push(point);
    if (this.points.length > TRACK_CAPACITY) {
      // Halve the resolution and keep the newest point.
      const kept = this.points.filter((_, i) => i % 2 === 0);
      if (kept[kept.length - 1] !== point) kept.push(point);
      this.points.splice(0, this.points.length, ...kept);
    }
  }
}

export class SessionStatistics {
  maxAltitude: Extreme | undefined;
  maxGroundSpeed: Extreme | undefined;
  /** Lowest remaining charge in percent (when the vehicle reports it). */
  minBatteryPercent: Extreme | undefined;
  minBatteryVoltage: Extreme | undefined;
  private readonly local = new DecimatedTrack();
  private readonly gps = new DecimatedTrack();
  private origin: { lat: number; lon: number } | undefined;

  /** The track to draw: local NED when the session had any, else GPS. */
  get track(): { source: 'local' | 'gps' | undefined; points: TrackPoint[] } {
    if (this.local.points.length) return { source: 'local', points: this.local.points };
    if (this.gps.points.length) return { source: 'gps', points: this.gps.points };
    return { source: undefined, points: [] };
  }

  /** Feed one telemetry event (name and data as the sidecar sends them). */
  add(name: string, data: Record<string, unknown>, time: string): void {
    switch (name) {
      case 'position': this.position(data, time); break;
      case 'local_position': {
        const x = num(data.x);
        const y = num(data.y);
        if (x !== undefined && y !== undefined) this.local.add({ east: y, north: x });
        break;
      }
      case 'vfr': this.maxGroundSpeed = higher(this.maxGroundSpeed, num(data.groundspeed), time); break;
      case 'battery':
        this.minBatteryPercent = lower(this.minBatteryPercent, num(data.remaining), time);
        this.minBatteryVoltage = lower(this.minBatteryVoltage, num(data.voltage), time);
        break;
      default: break;
    }
  }

  private position(data: Record<string, unknown>, time: string): void {
    this.maxAltitude = higher(this.maxAltitude, num(data.relativeAlt), time);
    const lat = num(data.lat);
    const lon = num(data.lon);
    if (lat === undefined || lon === undefined || (lat === 0 && lon === 0)) return;
    this.origin ??= { lat, lon };
    const { origin } = this;
    this.gps.add({
      east: (lon - origin.lon) * RAD * EARTH_RADIUS_M * Math.cos(origin.lat * RAD),
      north: (lat - origin.lat) * RAD * EARTH_RADIUS_M,
    });
  }
}

function higher(current: Extreme | undefined, value: number | undefined, time: string): Extreme | undefined {
  return value !== undefined && (!current || value > current.value) ? { value, time } : current;
}

function lower(current: Extreme | undefined, value: number | undefined, time: string): Extreme | undefined {
  return value !== undefined && (!current || value < current.value) ? { value, time } : current;
}
