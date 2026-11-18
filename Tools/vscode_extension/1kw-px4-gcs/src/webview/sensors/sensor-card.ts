// One Sensor Bench card: title, source, rate, age, a stale flag, labelled
// rows and an optional "rate not raised" note.
import { el, setText } from '../dom-helpers';
import { ageText, DASH, fmt } from '../format/telemetry-format';
import { WebviewState } from '../webview-state';

export interface CardRow {
  label: string;
  value(data: Record<string, unknown>): string;
}

export class SensorCard {
  readonly root = el('article', { className: 'sensor-card' });
  private readonly source = el('span', { className: 'card-source' });
  private readonly meta = el('span', { className: 'card-meta' });
  private readonly note = el('p', { className: 'card-note' });
  private readonly values: HTMLElement[];

  constructor(title: string, private readonly key: string, private readonly rows: CardRow[]) {
    const list = el('dl', { className: 'card-rows' });
    this.values = rows.map((row) => {
      const value = el('dd', { text: DASH });
      list.append(el('dt', { text: row.label }), value);
      return value;
    });
    this.note.hidden = true;
    this.root.append(el('header', { className: 'card-head' }, el('h3', { text: title }), this.source, this.meta), list, this.note);
  }

  setNote(text: string | null): void {
    this.note.hidden = !text;
    setText(this.note, text ?? '');
  }

  render(state: WebviewState): void {
    const data = state.value(this.key);
    const stale = state.isStale(this.key);
    this.root.classList.toggle('stale', stale);
    const age = state.ageMs(this.key);
    setText(this.source, data && typeof data.source === 'string' ? data.source : '');
    setText(this.meta, data ? `${fmt(state.rateHz(this.key), 1, 'Hz')} · ${ageText(age ?? NaN)}${stale ? ' · stale' : ''}`
      : 'no data');
    this.rows.forEach((row, index) => setText(this.values[index], data ? row.value(data) : DASH));
  }
}
