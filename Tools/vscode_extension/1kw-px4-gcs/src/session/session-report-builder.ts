// Builds the session report from the journal and the whole-session
// statistics: summary, connections and link changes, mode and arming
// timeline, status text, guarded commands, parameter changes (old → new),
// recordings and log downloads, extremes, the track, and the console
// transcript. All vehicle and file text is escaped (see html-escape.ts).
// No `vscode` import.
import { html, Raw } from './html-escape';
import { JournalEntry, SessionJournal } from './session-journal';
import { Extreme, SessionStatistics } from './session-statistics';
import { page, table, trackSvg } from './session-report-template';

export interface ReportInput {
  journal: SessionJournal;
  statistics: SessionStatistics;
  /** First connection of the session (ISO), when there was one. */
  started?: string;
  generated: Date;
  extensionVersion: string;
}

const SEVERITY = ['EMERGENCY', 'ALERT', 'CRITICAL', 'ERROR', 'WARNING', 'NOTICE', 'INFO', 'DEBUG'];

const time = (iso: string): string => iso.replace('T', ' ').replace(/\.\d+Z$/, 'Z');
const text = (value: unknown): string => (value === undefined || value === null ? '' : String(value));
const time_ = { title: 'Time (UTC)', className: 'time' };

function extreme(label: string, value: Extreme | undefined, unit: string, digits: number): unknown[] {
  return value ? [label, `${value.value.toFixed(digits)} ${unit}`, time(value.time)] : [label, 'not reported', ''];
}

function linkRows(entries: JournalEntry[]): unknown[][] {
  return entries.filter((e) => e.kind === 'connection' || e.kind === 'link').map((e) => {
    const d = e.data;
    if (e.kind === 'link') return [time(e.time), `link ${text(d.state)}`, ''];
    if (d.state !== 'connected') return [time(e.time), 'disconnected', ''];
    const where = d.transport === 'udp' ? `UDP ${text(d.host)}:${text(d.udpPort)}` : `serial ${text(d.port)} @ ${text(d.baud)}`;
    return [time(e.time), `connected to system ${text(d.systemId)}`, where];
  });
}

function flightRows(entries: JournalEntry[]): unknown[][] {
  return entries.filter((e) => e.kind === 'mode' || e.kind === 'arming').map((e) => (e.kind === 'mode'
    ? [time(e.time), `mode ${text(e.data.mode)}`, e.data.from ? `from ${text(e.data.from)}` : 'first seen']
    : [time(e.time), e.data.armed ? 'ARMED' : 'disarmed', '']));
}

function statusRows(entries: JournalEntry[]): unknown[][] {
  return entries.filter((e) => e.kind === 'statustext').map((e) => {
    const sev = Number(e.data.severity);
    const name = SEVERITY[sev] ?? text(e.data.severity);
    return [time(e.time), html`<span class="sev-${Number.isInteger(sev) ? sev : 'x'}">${name}</span>`,
      text(e.data.text) + (e.data.partial ? ' (incomplete)' : '')];
  });
}

function commandRows(entries: JournalEntry[]): unknown[][] {
  return entries.filter((e) => e.kind === 'command').map((e) => [time(e.time),
    text(e.data.action) + (e.data.mode ? ` ${text(e.data.mode)}` : ''), text(e.data.decision), text(e.data.result),
    text(e.data.message)]);
}

function paramRows(entries: JournalEntry[]): unknown[][] {
  const rows: unknown[][] = [];
  for (const e of entries) {
    if (e.kind === 'param_write') {
      rows.push([time(e.time), text(e.data.name), text(e.data.old), text(e.data.requested), text(e.data.value),
        text(e.data.result) + (e.data.message ? `: ${text(e.data.message)}` : '')]);
    } else if (e.kind === 'param_import') {
      rows.push([time(e.time), `import (${text(e.data.origin)})`, '', '', '', `${text(e.data.result)}: ${text(e.data.message)}`]);
    }
  }
  return rows;
}

function fileRows(entries: JournalEntry[]): unknown[][] {
  return entries.filter((e) => e.kind === 'recording' || e.kind === 'log_download').map((e) => {
    const d = e.data;
    if (e.kind === 'recording') {
      const detail = d.state === 'stopped' ? `stopped (${text(d.reason)})${d.frames != null ? `, ${text(d.frames)} frames` : ''}` : 'started';
      return [time(e.time), `.tlog ${detail}`, text(d.path)];
    }
    return [time(e.time), `log ${text(d.id)} download ${text(d.result)}`, text(d.path) || text(d.message)];
  });
}

function consoleText(entries: JournalEntry[]): Raw {
  const lines = entries.filter((e) => e.kind === 'console_line').map((e) => `${time(e.time)}  ${text(e.data.line)}`);
  const opened = entries.some((e) => e.kind === 'console_opened');
  if (!lines.length) return html`<p class="note">${opened ? 'The console was opened but printed nothing.' : 'The console was not used.'}</p>`;
  return html`<pre>${lines.join('\n')}</pre>`;
}

/** The most recent connection: vehicle and link as text. */
function lastLink(entries: JournalEntry[]): [string, string] {
  const last = [...entries].reverse().find((e) => e.kind === 'connection' && e.data.state === 'connected');
  if (!last) return ['none', 'none'];
  const d = last.data;
  const where = d.transport === 'udp' ? `UDP ${text(d.host)}:${text(d.udpPort)}`
    : `serial ${text(d.port)}${d.baud ? ` @ ${text(d.baud)}` : ''}`;
  return [d.systemId === null || d.systemId === undefined ? 'unknown' : `system ${text(d.systemId)}`, where];
}

function duration(startIso: string | undefined, end: Date): string {
  if (!startIso) return '';
  const seconds = Math.max(0, Math.round((end.getTime() - Date.parse(startIso)) / 1000));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h ? `${h} h ` : ''}${m} min ${seconds % 60} s`;
}

export function buildSessionReport(input: ReportInput): string {
  const entries = input.journal.entries();
  const generated = input.generated.toISOString();
  const { statistics: stats } = input;
  const track = stats.track;
  const counts = (kind: JournalEntry['kind']): number => entries.filter((e) => e.kind === kind).length;
  const [vehicle, link] = lastLink(entries);
  const body = html`
<h2>Summary</h2>
${table([{ title: 'Item' }, { title: 'Value' }], [
    ['Session start (first connection)', input.started ? time(input.started) : 'never connected'],
    ['Report generated', time(generated)],
    ['Session length (to the report)', duration(input.started, input.generated) || 'never connected'],
    ['Vehicle (last connection)', vehicle],
    ['Link (last connection)', link],
    ['Journal entries', String(entries.length)],
    ['Entries dropped (journal full)', String(input.journal.dropped)],
    ['Status messages', String(counts('statustext'))],
    ['Guarded commands', String(counts('command'))],
    ['Parameter writes', String(counts('param_write'))],
    ['Extension version', input.extensionVersion],
  ], '')}
${input.journal.dropped ? html`<p class="note">The oldest ${input.journal.dropped} journal entries were dropped; the
 sections below start later than the session.</p>` : ''}
<h2>Connections and link</h2>
${table([time_, { title: 'Event' }, { title: 'Detail' }], linkRows(entries), 'No connection in this session.')}
<h2>Flight mode and arming</h2>
${table([time_, { title: 'Change' }, { title: 'Detail' }], flightRows(entries), 'No heartbeat was received.')}
<h2>Extremes</h2>
${table([{ title: 'Figure' }, { title: 'Value', className: 'num' }, time_], [
    extreme('Highest altitude above home', stats.maxAltitude, 'm', 1),
    extreme('Fastest ground speed', stats.maxGroundSpeed, 'm/s', 1),
    extreme('Lowest battery charge', stats.minBatteryPercent, '%', 0),
    extreme('Lowest battery voltage', stats.minBatteryVoltage, 'V', 2),
  ], '')}
<h2>Track</h2>
${track.source ? html`<p class="note">Source: ${track.source === 'local' ? 'local position (NED)' : 'GPS'}, ${track.points.length} points.</p>` : ''}
${trackSvg(track.points)}
<h2>Status messages</h2>
${table([time_, { title: 'Severity' }, { title: 'Text' }], statusRows(entries), 'No status messages.')}
<h2>Guarded commands</h2>
${table([time_, { title: 'Command' }, { title: 'Decision' }, { title: 'Result' }, { title: 'Message' }], commandRows(entries),
    'No guarded commands.')}
<h2>Parameter changes</h2>
${table([time_, { title: 'Parameter' }, { title: 'Old' }, { title: 'Requested' }, { title: 'Now' }, { title: 'Result' }],
    paramRows(entries), 'No parameter changes.')}
<h2>Recordings and log downloads</h2>
${table([time_, { title: 'Event' }, { title: 'File' }], fileRows(entries), 'No recordings or log downloads.')}
<h2>Console</h2>
${consoleText(entries)}
`;
  return page('PX4 GCS session report', time(generated), body);
}
