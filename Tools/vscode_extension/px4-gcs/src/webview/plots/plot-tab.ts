// Plots tab: one uPlot strip chart per selected series (units differ, so each
// has its own y axis) over a shared 30 s, 2 min or 10 min window ending at the
// newest sample. Data come from the session history; charts redraw at most
// once per history change while the tab is visible.
import uPlot from 'uplot';
import { el, setText } from '../dom-helpers';
import { TabStateBanner } from '../tab-state-banner';
import { TabView } from '../tab-router';
import { postToHost, WebviewState } from '../webview-state';
import { DEFAULT_SERIES, PLOT_WINDOWS, PlotSeries, seriesCatalog, windowData } from './plot-series-catalog';

const CHART_HEIGHT = 150;
const WINDOW_LABELS: Record<number, string> = { 30: '30 s', 120: '2 min', 600: '10 min' };

function cssVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

interface Chart {
  series: PlotSeries;
  plot: uPlot;
  wrap: HTMLElement;
  empty: HTMLElement;
}

export class PlotTab implements TabView {
  readonly root = el('div', { className: 'plots-tab' });
  private readonly banner = new TabStateBanner('Waiting for telemetry history…');
  private readonly content = el('div', { className: 'plots-content' });
  private readonly picker = el('fieldset', { className: 'plot-picker' }, el('legend', { text: 'Series' }));
  private readonly windowSelect = el('select', { attrs: { 'aria-label': 'Plot window' } });
  private readonly charts = el('div', { className: 'plot-charts' });
  private readonly boxes = new Map<string, HTMLInputElement>();
  private readonly selected = new Set<string>(DEFAULT_SERIES);
  private active: Chart[] = [];
  private windowSeconds: number = PLOT_WINDOWS[0];
  private end = 0;
  private drawn = '';
  private requested = false;
  private visible = false;
  private readonly resize = new ResizeObserver(() => this.fitWidth());

  constructor(private readonly state: WebviewState) {
    for (const seconds of PLOT_WINDOWS) {
      this.windowSelect.appendChild(el('option', { text: WINDOW_LABELS[seconds], attrs: { value: String(seconds) } }));
    }
    this.windowSelect.addEventListener('change', () => {
      this.windowSeconds = Number(this.windowSelect.value);
      this.drawn = '';
    });
    const tools = el('div', { className: 'plot-tools' }, el('label', {}, 'Window ', this.windowSelect));
    this.content.append(tools, this.picker, this.charts);
    this.root.append(this.banner.root, this.content);
    this.resize.observe(this.charts);
  }

  show(visible: boolean): void {
    this.visible = visible;
    if (!visible) return;
    this.drawn = '';
    if (!this.requested && !this.state.history.seeded) {
      this.requested = true;
      postToHost({ type: 'history_request' });
    }
  }

  frame(): void {
    const history = this.state.history;
    const latest = history.latestTs();
    this.banner.update(latest !== undefined ? 'live' : this.state.connected ? 'waiting' : 'disconnected', this.content);
    if (latest === undefined) return;
    const catalog = seriesCatalog(history.keys('named_value:'));
    this.syncPicker(catalog);
    this.syncCharts(catalog);
    const key = `${history.version}:${this.windowSeconds}:${this.active.map((c) => c.series.id).join(',')}`;
    if (key === this.drawn) return;
    this.drawn = key;
    this.end = latest;
    for (const chart of this.active) {
      const data = windowData(history.get(chart.series.key), chart.series, this.end, this.windowSeconds);
      const hasData = data[1].some((v) => v !== null);
      chart.empty.hidden = hasData;
      setText(chart.empty, hasData ? '' : `No ${chart.series.label} data in this window.`);
      chart.plot.setData(data);
    }
  }

  private syncPicker(catalog: PlotSeries[]): void {
    for (const series of catalog) {
      if (this.boxes.has(series.id)) continue;
      const box = el('input', { attrs: { type: 'checkbox', id: `plot-${series.id}` } });
      box.checked = this.selected.has(series.id);
      box.addEventListener('change', () => {
        if (box.checked) this.selected.add(series.id);
        else this.selected.delete(series.id);
        this.drawn = '';
      });
      this.boxes.set(series.id, box);
      const label = series.units ? `${series.label} (${series.units})` : series.label;
      this.picker.appendChild(el('label', { className: 'plot-choice', attrs: { for: `plot-${series.id}` } }, box, ` ${label}`));
    }
  }

  /** Create charts for newly selected series and destroy the deselected ones, keeping catalog order. */
  private syncCharts(catalog: PlotSeries[]): void {
    const wanted = catalog.filter((s) => this.selected.has(s.id));
    if (wanted.map((s) => s.id).join(',') === this.active.map((c) => c.series.id).join(',')) return;
    const keep = new Map(this.active.map((c) => [c.series.id, c]));
    const next: Chart[] = [];
    for (const series of wanted) next.push(keep.get(series.id) ?? this.createChart(series));
    for (const chart of this.active) {
      if (!next.includes(chart)) {
        chart.plot.destroy();
        chart.wrap.remove();
      }
    }
    for (const chart of next) this.charts.appendChild(chart.wrap);
    this.active = next;
  }

  private createChart(series: PlotSeries): Chart {
    const fg = cssVar('--vscode-foreground', '#cccccc');
    const grid = cssVar('--vscode-panel-border', 'rgba(128,128,128,0.35)');
    const wrap = el('div', { className: 'plot-chart' });
    const empty = el('p', { className: 'plot-empty' });
    const title = series.units ? `${series.label} (${series.units})` : series.label;
    const axis = { stroke: fg, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid, width: 1 } };
    const plot = new uPlot({
      title,
      width: Math.max(this.charts.clientWidth - 4, 200),
      height: CHART_HEIGHT,
      legend: { show: true },
      cursor: { drag: { x: false, y: false } },
      scales: {
        x: { time: true, range: () => [this.end - this.windowSeconds, this.end] },
      },
      axes: [axis, { ...axis, size: 60 }],
      series: [{}, { label: series.label, stroke: '#ED6C00', width: 1.5, spanGaps: false }],
    }, [[], []], wrap);
    wrap.appendChild(empty);
    return { series, plot, wrap, empty };
  }

  private fitWidth(): void {
    if (!this.visible) return;
    const width = Math.max(this.charts.clientWidth - 4, 200);
    for (const chart of this.active) chart.plot.setSize({ width, height: CHART_HEIGHT });
  }
}
