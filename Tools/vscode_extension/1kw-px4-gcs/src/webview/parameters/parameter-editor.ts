// Edit panel of one parameter: description, units, range, default, reboot
// note, enumeration or bitmask choices and a value field. "Write" posts the
// text to the host, which validates, confirms when the policy asks and writes.
import { ParamEntry, ParamOutcomeView } from '../../dashboard/dashboard-messages';
import { button, clear, el, setText } from '../dom-helpers';
import { formatParamValue } from '../format/telemetry-format';
import { postToHost } from '../webview-state';

/** Value of a bitmask from the checked bit indices. */
export function bitmaskValue(bits: number[]): number {
  return bits.reduce((sum, bit) => sum + 2 ** bit, 0);
}

/** "0 .. 20 m/s", "min 0", "" */
export function rangeText(entry: ParamEntry): string {
  const meta = entry.meta;
  if (!meta) return '';
  const unit = meta.units ? ` ${meta.units}` : '';
  const f = (v: number): string => formatParamValue(v, entry.type);
  if (meta.min !== undefined && meta.max !== undefined) return `${f(meta.min)} .. ${f(meta.max)}${unit}`;
  if (meta.min !== undefined) return `min ${f(meta.min)}${unit}`;
  if (meta.max !== undefined) return `max ${f(meta.max)}${unit}`;
  return '';
}

export class ParameterEditor {
  readonly root = el('section', { className: 'param-editor', attrs: { 'aria-label': 'Edit parameter' } });
  private readonly title = el('h3');
  private readonly body = el('div', { className: 'param-editor-body' });
  private readonly input = el('input', { attrs: { type: 'text', 'aria-label': 'New value', spellcheck: 'false' } });
  private readonly choices = el('div', { className: 'param-choices' });
  private readonly outcome = el('div', { className: 'param-outcome', attrs: { role: 'status', 'aria-live': 'polite' } });
  private name: string | undefined;

  constructor() {
    const write = button('Write', () => this.write(), { className: 'primary' });
    const close = button('Close', () => this.close());
    this.input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') this.write();
      if (event.key === 'Escape') this.close();
    });
    this.root.append(el('div', { className: 'param-editor-head' }, this.title, close), this.body, this.choices,
      el('div', { className: 'param-editor-row' }, this.input, write), this.outcome);
    this.root.hidden = true;
  }

  get openName(): string | undefined {
    return this.name;
  }

  open(entry: ParamEntry): void {
    this.name = entry.name;
    this.root.hidden = false;
    this.fill(entry);
    this.input.value = entry.value === null ? '' : formatParamValue(entry.value, entry.type);
    setText(this.outcome, '');
    this.input.focus();
  }

  /** The row changed (write result, refresh): show its current value and metadata. */
  refresh(entry: ParamEntry | undefined, outcome: ParamOutcomeView | undefined): void {
    if (!this.name || !entry || entry.name !== this.name) return;
    this.fill(entry);
    if (outcome && outcome.name === this.name) {
      setText(this.outcome, outcome.message);
      this.outcome.className = `param-outcome${outcome.result === 'applied' ? '' : ' warn'}`;
    }
  }

  close(): void {
    this.name = undefined;
    this.root.hidden = true;
  }

  private write(): void {
    if (this.name) postToHost({ type: 'param_edit', name: this.name, value: this.input.value });
  }

  private fill(entry: ParamEntry): void {
    const meta = entry.meta;
    setText(this.title, entry.name);
    clear(this.body);
    const line = (label: string, value: string | undefined): void => {
      if (value) this.body.appendChild(el('div', {}, el('span', { className: 'param-label', text: `${label}: ` }), value));
    };
    if (meta?.shortDesc) this.body.appendChild(el('div', { className: 'param-short', text: meta.shortDesc }));
    if (meta?.longDesc) this.body.appendChild(el('div', { className: 'param-long', text: meta.longDesc }));
    line('Current', `${formatParamValue(entry.value, entry.type)}${meta?.units ? ` ${meta.units}` : ''} (${entry.type})`);
    line('Build default', meta?.default !== undefined ? formatParamValue(meta.default, entry.type) : undefined);
    line('Range', rangeText(entry));
    if (meta?.rebootRequired) this.body.appendChild(el('div', { className: 'warn', text: 'Takes effect after a reboot.' }));
    if (meta?.typeMismatch) {
      this.body.appendChild(el('div', { className: 'warn', text: `Metadata type ${meta.typeMismatch} differs from the vehicle.` }));
    }
    if (!meta) this.body.appendChild(el('div', { className: 'warn', text: 'No metadata for this parameter.' }));
    this.fillChoices(entry);
  }

  private fillChoices(entry: ParamEntry): void {
    clear(this.choices);
    const meta = entry.meta;
    if (meta?.values) {
      const select = el('select', { attrs: { 'aria-label': 'Choices' } },
        el('option', { text: 'Choose…', attrs: { value: '' } }));
      for (const v of meta.values) select.appendChild(el('option', { text: `${v.value}: ${v.description}`, attrs: { value: String(v.value) } }));
      select.value = meta.values.some((v) => v.value === entry.value) ? String(entry.value) : '';
      select.addEventListener('change', () => { if (select.value !== '') this.input.value = select.value; });
      this.choices.appendChild(select);
    } else if (meta?.bitmask) {
      const current = entry.value ?? 0;
      const boxes: { bit: number; box: HTMLInputElement }[] = [];
      for (const b of meta.bitmask) {
        const box = el('input', { attrs: { type: 'checkbox' } });
        box.checked = Math.floor(current / 2 ** b.index) % 2 === 1;
        box.addEventListener('change', () => {
          this.input.value = String(bitmaskValue(boxes.filter((x) => x.box.checked).map((x) => x.bit)));
        });
        boxes.push({ bit: b.index, box });
        this.choices.appendChild(el('label', { className: 'param-bit' }, box, ` ${b.index}: ${b.description}`));
      }
    }
  }
}
