// Track geometry without tiles: positions become metres east and north of a
// home point. Local NED (LOCAL_POSITION_NED) is used as it is; otherwise
// GLOBAL_POSITION_INT is projected equirectangularly around the first fix
// with the WGS84 radii of curvature at that latitude (well under 1 m of error
// over 1 km). No DOM access (loaded by the tests).
import { SampleMessage } from '../../dashboard/dashboard-messages';

const WGS84_A = 6378137;
const WGS84_E2 = 6.69437999014e-3;
const DEG = Math.PI / 180;

export interface LatLon {
  lat: number;
  lon: number;
}

/** Metres east and north of home. */
export interface EastNorth {
  east: number;
  north: number;
}

export interface TrackPoint extends EastNorth {
  ts: number;
}

export type TrackSource = 'local' | 'global';

export interface Track {
  source: TrackSource;
  /** What the home marker stands for. */
  homeLabel: string;
  /** Global home (first fix) when the track is projected from GLOBAL_POSITION_INT. */
  home?: LatLon;
  points: TrackPoint[];
}

/** Meridional (north) and prime-vertical (east) radii of curvature at a latitude in degrees. */
export function radiiOfCurvature(latDeg: number): { meridional: number; primeVertical: number } {
  const s = Math.sin(latDeg * DEG);
  const w = 1 - WGS84_E2 * s * s;
  return { meridional: (WGS84_A * (1 - WGS84_E2)) / (w * Math.sqrt(w)), primeVertical: WGS84_A / Math.sqrt(w) };
}

/** Equirectangular projection of `p` around `origin` (metres east and north). */
export function project(origin: LatLon, p: LatLon): EastNorth {
  const midLat = (origin.lat + p.lat) / 2;
  const { meridional, primeVertical } = radiiOfCurvature(midLat);
  let dLon = p.lon - origin.lon;
  if (dLon > 180) dLon -= 360;
  if (dLon < -180) dLon += 360;
  return {
    east: dLon * DEG * primeVertical * Math.cos(midLat * DEG),
    north: (p.lat - origin.lat) * DEG * meridional,
  };
}

/** Distance in metres and bearing in degrees (0 = north, clockwise) from `a` to `b`. */
export function distanceBearing(a: EastNorth, b: EastNorth): { distance: number; bearing: number } {
  const de = b.east - a.east;
  const dn = b.north - a.north;
  const bearing = (Math.atan2(de, dn) / DEG + 360) % 360;
  return { distance: Math.hypot(de, dn), bearing };
}

function num(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

/** A usable global fix: finite and not the 0/0 PX4 sends without one. */
function latLon(data: Record<string, unknown>): LatLon | undefined {
  const lat = num(data.lat);
  const lon = num(data.lon);
  if (lat === undefined || lon === undefined || (lat === 0 && lon === 0)) return undefined;
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return undefined;
  return { lat, lon };
}

/**
 * The track from the session history: local NED when the estimator provides
 * it, otherwise global positions around the first fix; undefined when neither
 * exists (the empty state names the missing data).
 */
export function buildTrack(local: readonly SampleMessage[], global: readonly SampleMessage[]): Track | undefined {
  const localPoints: TrackPoint[] = [];
  for (const { ts, data } of local) {
    const north = num(data.x);
    const east = num(data.y);
    if (north !== undefined && east !== undefined) localPoints.push({ ts, east, north });
  }
  if (localPoints.length > 0) return { source: 'local', homeLabel: 'local origin', points: localPoints };
  let home: LatLon | undefined;
  const points: TrackPoint[] = [];
  for (const { ts, data } of global) {
    const fix = latLon(data);
    if (!fix) continue;
    home ??= fix;
    points.push({ ts, ...project(home, fix) });
  }
  return home ? { source: 'global', homeLabel: 'first fix', home, points } : undefined;
}

/** Text for the empty Track tab. */
export const NO_POSITION_TEXT = 'No position: the vehicle sends neither LOCAL_POSITION_NED nor a GLOBAL_POSITION_INT fix. '
  + 'Indoors without GPS the estimator has no position to report.';

export interface ScaleBar {
  meters: number;
  pixels: number;
  label: string;
}

/** The longest 1, 2 or 5 × 10^n metre bar that fits in `maxPixels` at `metersPerPixel`. */
export function scaleBar(metersPerPixel: number, maxPixels: number): ScaleBar {
  const limit = metersPerPixel * maxPixels;
  let meters = 10 ** Math.floor(Math.log10(limit));
  for (const step of [5, 2, 1]) {
    if (step * meters <= limit) {
      meters *= step;
      break;
    }
  }
  const label = meters >= 1000 ? `${meters / 1000} km` : meters >= 1 ? `${meters} m` : `${Math.round(meters * 100)} cm`;
  return { meters, pixels: meters / metersPerPixel, label };
}

/** Bounds of a set of points (for Fit), with a floor so a single point still has a scale. */
export function trackBounds(points: readonly EastNorth[], minSpan = 10): { center: EastNorth; span: EastNorth } {
  let minE = Infinity;
  let maxE = -Infinity;
  let minN = Infinity;
  let maxN = -Infinity;
  for (const p of points) {
    minE = Math.min(minE, p.east);
    maxE = Math.max(maxE, p.east);
    minN = Math.min(minN, p.north);
    maxN = Math.max(maxN, p.north);
  }
  if (!Number.isFinite(minE)) return { center: { east: 0, north: 0 }, span: { east: minSpan, north: minSpan } };
  return {
    center: { east: (minE + maxE) / 2, north: (minN + maxN) / 2 },
    span: { east: Math.max(maxE - minE, minSpan), north: Math.max(maxN - minN, minSpan) },
  };
}

/** What the Track canvas shows: the centre point and the zoom. */
export interface TrackView {
  center: EastNorth;
  metersPerPixel: number;
}

export interface CanvasSize {
  width: number;
  height: number;
}

/** Canvas pixel of a point (y grows down, north is up). */
export function toScreen(view: TrackView, size: CanvasSize, p: EastNorth): { x: number; y: number } {
  return {
    x: size.width / 2 + (p.east - view.center.east) / view.metersPerPixel,
    y: size.height / 2 - (p.north - view.center.north) / view.metersPerPixel,
  };
}

/** A view that shows every point with a 10% margin (home included by the caller). */
export function fitView(points: readonly EastNorth[], size: CanvasSize): TrackView {
  const { center, span } = trackBounds(points);
  const width = Math.max(size.width, 1);
  const height = Math.max(size.height, 1);
  return { center, metersPerPixel: (Math.max(span.east / width, span.north / height)) * 1.2 };
}
