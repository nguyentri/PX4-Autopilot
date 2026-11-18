// Pure display formatting for telemetry: fixed decimals, units, angle wrap.
// No DOM access, so the logic tests import it directly.

export const DASH = '—';

export function isNum(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** Fixed decimals with unit; a dash for missing or non-finite values. */
export function fmt(value: unknown, decimals = 1, unit = ''): string {
  if (!isNum(value)) return DASH;
  const text = value.toFixed(decimals);
  const clean = /^-0(\.0+)?$/.test(text) ? text.slice(1) : text;
  return unit ? `${clean} ${unit}` : clean;
}

export function radToDeg(rad: number): number {
  return (rad * 180) / Math.PI;
}

/** Angle in degrees wrapped to [0, 360). */
export function wrap360(deg: number): number {
  const wrapped = deg % 360;
  return wrapped < 0 ? wrapped + 360 : wrapped === 0 ? 0 : wrapped;
}

/** Angle in degrees wrapped to (-180, 180]. */
export function wrap180(deg: number): number {
  const wrapped = wrap360(deg);
  return wrapped > 180 ? wrapped - 360 : wrapped;
}

/** Age of a sample as short text: "0.4 s", "12 s", "3 min". */
export function ageText(ms: number): string {
  if (!isNum(ms) || ms < 0) return DASH;
  if (ms < 10000) return `${(ms / 1000).toFixed(1)} s`;
  if (ms < 120000) return `${Math.round(ms / 1000)} s`;
  return `${Math.round(ms / 60000)} min`;
}

export const SEVERITY_NAMES = ['EMERGENCY', 'ALERT', 'CRITICAL', 'ERROR', 'WARNING', 'NOTICE', 'INFO', 'DEBUG'];

export function severityName(severity: number): string {
  return SEVERITY_NAMES[severity] ?? `SEVERITY ${severity}`;
}

/** CSS class of a severity: error (0-3), warn (4), info (5-7). */
export function severityClass(severity: number): 'error' | 'warn' | 'info' {
  if (severity <= 3) return 'error';
  return severity === 4 ? 'warn' : 'info';
}

const FIX_NAMES = ['No GPS', 'No fix', '2D fix', '3D fix', 'DGPS', 'RTK float', 'RTK fixed', 'Static', 'PPP'];

export function gpsFixName(fixType: unknown): string {
  return isNum(fixType) ? FIX_NAMES[fixType] ?? `Fix ${fixType}` : DASH;
}

/** Parameter value by MAVLink type: integers without decimals, floats with up to 6 significant digits. */
export function formatParamValue(value: unknown, type: string): string {
  if (!isNum(value)) return DASH;
  if (/INT/i.test(type)) return String(Math.trunc(value));
  if (value !== 0 && (Math.abs(value) >= 1e6 || Math.abs(value) < 1e-4)) return value.toExponential(4);
  return String(Number(value.toPrecision(6)));
}

/** Three-axis vector as "x, y, z" with fixed decimals. */
export function vec3(value: unknown, decimals = 2): string {
  if (!Array.isArray(value) || value.length < 3) return DASH;
  return value.slice(0, 3).map((v) => fmt(v, decimals)).join(', ');
}

/** Clock time of a sidecar timestamp (seconds since the epoch), local time. */
export function clockTime(ts: number): string {
  const d = new Date(ts * 1000);
  const two = (n: number): string => String(n).padStart(2, '0');
  return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
}
