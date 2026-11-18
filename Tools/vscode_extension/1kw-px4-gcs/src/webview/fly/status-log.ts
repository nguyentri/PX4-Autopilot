// STATUSTEXT log with a severity filter and Copy. Vehicle text is only ever a
// text node. New errors are announced through the log's live region.
import { StatusEntry } from '../../dashboard/dashboard-messages';
import { button, clear, el } from '../dom-helpers';
import { clockTime, severityClass, severityName } from '../format/telemetry-format';
import { postToHost } from '../webview-state';

/** Highest severity number shown for each filter choice (MAVLink: lower is worse). */
export const SEVERITY_FILTERS: { label: string; max: number }[] = [
  { label: 'All', max: 7 },
  { label: 'Info and worse', max: 6 },
  { label: 'Warnings and errors', max: 4 },
  { label: 'Errors only', max: 3 },
];

export function filterStatus(entries: StatusEntry[], max: number): StatusEntry[] {
  return entries.filter((entry) => entry.severity <= max);
}

export function statusLine(entry: StatusEntry): string {
  return `${clockTime(entry.ts)} ${severityName(entry.severity)} ${entry.text}`;
}

const MAX_ROWS = 500;

export class StatusLog {
  private readonly list = el('ol', { className: 'status-list', attrs: { role: 'log', 'aria-live': 'polite', 'aria-label': 'Vehicle messages' } });
  private readonly filter = el('select', { attrs: { 'aria-label': 'Severity filter' } });
  readonly root = el('div', { className: 'status-log' });
  private entries: StatusEntry[] = [];
  private max = 7;

  constructor() {
    SEVERITY_FILTERS.forEach((choice, index) => {
      this.filter.appendChild(el('option', { text: choice.label, attrs: { value: String(index) } }));
    });
    this.filter.addEventListener('change', () => {
      this.max = SEVERITY_FILTERS[Number(this.filter.value)]?.max ?? 7;
      this.redraw();
    });
    const copy = button('Copy', () => postToHost({ type: 'copy', text: filterStatus(this.entries, this.max).map(statusLine).join('\n') }));
    this.root.append(el('div', { className: 'status-head' }, el('h2', { text: 'Messages' }), this.filter, copy), this.list);
  }

  reset(entries: StatusEntry[]): void {
    this.entries = entries.slice(-MAX_ROWS);
    this.redraw();
  }

  add(entries: StatusEntry[]): void {
    this.entries.push(...entries);
    if (this.entries.length > MAX_ROWS) this.entries.splice(0, this.entries.length - MAX_ROWS);
    for (const entry of filterStatus(entries, this.max)) this.list.appendChild(this.row(entry));
    while (this.list.childElementCount > MAX_ROWS) this.list.firstElementChild?.remove();
    this.list.scrollTop = this.list.scrollHeight;
  }

  private redraw(): void {
    clear(this.list);
    for (const entry of filterStatus(this.entries, this.max)) this.list.appendChild(this.row(entry));
    this.list.scrollTop = this.list.scrollHeight;
  }

  private row(entry: StatusEntry): HTMLLIElement {
    return el('li', { className: `status-row sev-${severityClass(entry.severity)}` },
      el('span', { className: 'status-time', text: clockTime(entry.ts) }),
      el('span', { className: 'status-sev', text: severityName(entry.severity) }),
      el('span', { className: 'status-text', text: entry.text }));
  }
}
