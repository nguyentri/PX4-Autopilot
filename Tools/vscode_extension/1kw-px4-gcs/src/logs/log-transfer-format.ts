// Byte, percent and rate text for log transfers; shared by the extension host
// (notifications, refusal message) and the Logs tab. Pure functions.
import { LogTransferView } from '../dashboard/dashboard-messages';

const MB = 1024 * 1024;

export function formatBytes(bytes: number): string {
  if (bytes >= MB) return `${(bytes / MB).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} kB`;
  return `${bytes} B`;
}

/** "120.0 kB of 400.0 kB (30 %), 12.5 kB/s" */
export function transferText(t: Pick<LogTransferView, 'received' | 'total' | 'rateBps'>): string {
  const percent = t.total > 0 ? Math.floor((100 * t.received) / t.total) : 0;
  return `${formatBytes(t.received)} of ${formatBytes(t.total)} (${percent} %), ${formatBytes(t.rateBps)}/s`;
}

/** LOG_ENTRY time as "2026-11-18 10:15:02 UTC", or "no date" when the vehicle had no clock. */
export function logDate(timeUtc: number | null): string {
  return timeUtc ? new Date(timeUtc * 1000).toISOString().replace('T', ' ').replace(/\.\d+Z$/, ' UTC') : 'no date';
}
