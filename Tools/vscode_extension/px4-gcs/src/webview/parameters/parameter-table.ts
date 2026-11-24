// Parameters tab: windowed rendering (only the rows in view exist in the DOM,
// about 1,400 parameters on PX4), search by name, the "differs from build
// default" filter, the metadata source line, Refresh, export and import, and
// the edit panel.
import { ParamEntry, ParamsState } from '../../dashboard/dashboard-messages';
import { button, clear, el, setText } from '../dom-helpers';
import { TabStateBanner } from '../tab-state-banner';
import { TabView } from '../tab-router';
import { postToHost, WebviewState } from '../webview-state';
import { ParameterEditor } from './parameter-editor';
import { parameterRow } from './parameter-row';

export const ROW_HEIGHT = 24;
const OVERSCAN = 8;

/** Rows [start, end) to render for a scroll position. */
export function visibleRange(scrollTop: number, viewport: number, rowHeight: number, count: number,
  overscan = OVERSCAN): { start: number; end: number } {
  const first = Math.floor(Math.max(0, scrollTop) / rowHeight);
  const start = Math.max(0, first - overscan);
  const end = Math.min(count, first + Math.ceil(Math.max(0, viewport) / rowHeight) + overscan);
  return { start, end: Math.max(start, end) };
}

/** Case-insensitive match of every space-separated term against the name; optionally only rows that differ. */
export function filterParams(params: ParamEntry[], query: string, differsOnly = false): ParamEntry[] {
  const terms = query.trim().toUpperCase().split(/\s+/).filter(Boolean);
  const rows = differsOnly ? params.filter((param) => param.differs === true) : params;
  if (terms.length === 0) return rows;
  return rows.filter((param) => {
    const name = param.name.toUpperCase();
    return terms.every((term) => name.includes(term));
  });
}

export function progressText(state: ParamsState): string {
  switch (state.state) {
    case 'loading': return `Loading ${state.received} / ${state.total ?? '?'}`;
    case 'done': return state.missing.length > 0
      ? `${state.params.length} parameters, ${state.missing.length} missing` : `${state.params.length} parameters`;
    case 'error': return `Failed: ${state.message}`;
    default: return '';
  }
}

export class ParameterTable implements TabView {
  readonly root = el('div', { className: 'params-tab' });
  private readonly banner = new TabStateBanner('Waiting for the parameter list…');
  private readonly search = el('input', { attrs: { type: 'search', placeholder: 'Search parameters', 'aria-label': 'Search parameters' } });
  private readonly progress = el('span', { className: 'params-progress', attrs: { role: 'status' } });
  private readonly viewport = el('div', { className: 'params-viewport', attrs: { role: 'table', 'aria-label': 'Parameters' } });
  private readonly spacer = el('div', { className: 'params-spacer' });
  private readonly content = el('div', { className: 'params-content' });
  private readonly differsOnly = el('input', { attrs: { type: 'checkbox' } });
  private readonly source = el('div', { className: 'params-source' });
  private readonly editor = new ParameterEditor();
  private all: ParamEntry[] = [];
  private shown: ParamEntry[] = [];
  private drawn = '';

  constructor(private readonly state: WebviewState) {
    const refresh = button('Refresh', () => postToHost({ type: 'params_refresh' }));
    const exportButton = button('Export…', () => postToHost({ type: 'run', command: 'exportParameters' }));
    const importButton = button('Import…', () => postToHost({ type: 'run', command: 'importParameters' }));
    const differs = el('label', { className: 'params-differs' }, this.differsOnly, ' Differs from build default');
    const header = el('div', { className: 'param-row param-header', attrs: { role: 'row' } },
      ...['Name', 'Value', 'Build default', 'Units', 'Differs from build default']
        .map((text) => el('span', { text, attrs: { role: 'columnheader' } })));
    this.viewport.appendChild(this.spacer);
    this.content.append(el('div', { className: 'params-head' }, this.search, differs, this.progress, refresh,
      exportButton, importButton), this.source, this.editor.root, header, this.viewport);
    this.root.append(this.banner.root, this.content);
    this.search.addEventListener('input', () => this.applyFilter());
    this.differsOnly.addEventListener('change', () => this.applyFilter());
    this.viewport.addEventListener('scroll', () => this.draw());
  }

  show(visible: boolean): void {
    if (visible) this.update();
  }

  update(): void {
    const params = this.state.params;
    const phase = !this.state.connected && params.state !== 'done' ? 'disconnected'
      : params.state === 'idle' ? 'waiting' : 'live';
    this.banner.update(phase, this.content);
    setText(this.progress, progressText(params));
    setText(this.source, params.state === 'done' ? `Metadata: ${params.metadata}` : '');
    const next = params.state === 'done' ? params.params : [];
    if (next !== this.all) {
      this.all = next;
      this.applyFilter();
      const open = this.editor.openName;
      this.editor.refresh(open ? next.find((p) => p.name === open) : undefined, this.state.paramOutcome);
    }
  }

  /** A write result arrived: show it in the editor. */
  showOutcome(): void {
    const open = this.editor.openName;
    this.editor.refresh(open ? this.all.find((p) => p.name === open) : undefined, this.state.paramOutcome);
  }

  private open(name: string): void {
    const entry = this.all.find((p) => p.name === name);
    if (entry) this.editor.open(entry);
  }

  private applyFilter(): void {
    const previousTop = this.viewport.scrollTop;
    this.shown = filterParams(this.all, this.search.value, this.differsOnly.checked);
    this.viewport.scrollTop = previousTop;
    this.spacer.style.height = `${this.shown.length * ROW_HEIGHT}px`;
    this.drawn = '';
    this.draw();
  }

  private draw(): void {
    const { start, end } = visibleRange(this.viewport.scrollTop, this.viewport.clientHeight || 400, ROW_HEIGHT, this.shown.length);
    const key = `${start}:${end}:${this.shown.length}`;
    if (key === this.drawn) return;
    this.drawn = key;
    clear(this.spacer);
    for (let i = start; i < end; i += 1) this.spacer.appendChild(parameterRow(this.shown[i], i * ROW_HEIGHT, ROW_HEIGHT,
      (name) => this.open(name)));
  }
}
