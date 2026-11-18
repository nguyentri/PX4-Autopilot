// MAVLink Inspector: one row per message seen (name, id, component, count,
// rate), the last decoded value inside <details>. The sidecar sends the list
// only while this tab is visible.
import { InspectorRow } from '../../dashboard/dashboard-messages';
import { el, setText } from '../dom-helpers';
import { fmt } from '../format/telemetry-format';
import { TabStateBanner } from '../tab-state-banner';
import { TabView } from '../tab-router';
import { WebviewState } from '../webview-state';

/** Stable row key: a message id can arrive from several components. */
export function inspectorKey(row: Pick<InspectorRow, 'id' | 'component'>): string {
  return `${row.id}:${row.component}`;
}

/** Sort by name, then component, so rows do not jump while rates change. */
export function sortInspector(rows: InspectorRow[]): InspectorRow[] {
  return [...rows].sort((a, b) => a.name.localeCompare(b.name) || a.component - b.component);
}

/** The decoded fields as indented text (shown in a <pre> text node). */
export function lastValueText(last: Record<string, unknown> | null): string {
  if (!last) return '';
  try {
    return JSON.stringify(last, null, 2);
  } catch {
    return String(last);
  }
}

interface RowNodes {
  root: HTMLDetailsElement;
  count: HTMLElement;
  rate: HTMLElement;
  body: HTMLElement;
  last: Record<string, unknown> | null;
}

export class InspectorTab implements TabView {
  readonly root = el('div', { className: 'inspector-tab' });
  private readonly banner = new TabStateBanner('Waiting for MAVLink messages…');
  private readonly summary = el('p', { className: 'inspector-summary', attrs: { role: 'status' } });
  private readonly list = el('div', { className: 'inspector-list' });
  private readonly content = el('div', {}, this.summary, this.list);
  private readonly rows = new Map<string, RowNodes>();
  private seen = 0;

  constructor(private readonly state: WebviewState) {
    this.root.append(this.banner.root, this.content);
  }

  show(visible: boolean): void {
    if (visible) this.updateBanner();
  }

  updateBanner(): void {
    this.banner.update(!this.state.connected ? 'disconnected' : this.seen > 0 ? 'live' : 'waiting', this.content);
  }

  update(messages: InspectorRow[], unknown: number): void {
    this.seen = messages.length;
    const wanted = new Set<string>();
    for (const row of sortInspector(messages)) {
      const key = inspectorKey(row);
      wanted.add(key);
      const nodes = this.rows.get(key) ?? this.createRow(row, key);
      nodes.last = row.last;
      setText(nodes.count, String(row.count));
      setText(nodes.rate, fmt(row.rateHz, 1, 'Hz'));
      if (nodes.root.open) setText(nodes.body, lastValueText(row.last));
      this.list.appendChild(nodes.root); // keeps sorted order; moving an element is cheap
    }
    for (const [key, nodes] of this.rows) {
      if (!wanted.has(key)) {
        nodes.root.remove();
        this.rows.delete(key);
      }
    }
    setText(this.summary, `${messages.length} message types${unknown > 0 ? ` · ${unknown} undecodable` : ''}`);
    this.updateBanner();
  }

  private createRow(row: InspectorRow, key: string): RowNodes {
    const count = el('span', { className: 'insp-count' });
    const rate = el('span', { className: 'insp-rate' });
    const body = el('pre', { className: 'insp-last' });
    const root = el('details', { className: 'insp-row' },
      el('summary', {},
        el('span', { className: 'insp-name', text: row.name }),
        el('span', { className: 'insp-id', text: `#${row.id} · comp ${row.component}` }),
        count, rate),
      body);
    const nodes: RowNodes = { root, count, rate, body, last: row.last };
    root.addEventListener('toggle', () => { if (root.open) setText(body, lastValueText(nodes.last)); });
    this.rows.set(key, nodes);
    return nodes;
  }
}
