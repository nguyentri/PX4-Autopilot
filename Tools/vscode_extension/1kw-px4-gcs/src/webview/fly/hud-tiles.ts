// Numeric HUD tiles. Each tile names the store key it reads, so it greys out
// on its own when that value stops updating.
import { el, setText } from '../dom-helpers';
import { DASH, fmt, gpsFixName, isNum } from '../format/telemetry-format';
import { WebviewState } from '../webview-state';

type Data = Record<string, unknown>;

interface TileSpec {
  label: string;
  key: string;
  value(data: Data): string;
  detail?(data: Data): string;
  warn?(data: Data): boolean;
}

const TILES: TileSpec[] = [
  { label: 'Altitude (rel)', key: 'position', value: (d) => fmt(d.relativeAlt, 1, 'm'), detail: (d) => `AMSL ${fmt(d.alt, 1, 'm')}` },
  { label: 'Climb', key: 'vfr', value: (d) => fmt(d.climb, 1, 'm/s') },
  { label: 'Ground speed', key: 'vfr', value: (d) => fmt(d.groundspeed, 1, 'm/s'), detail: (d) => `Air ${fmt(d.airspeed, 1, 'm/s')}` },
  { label: 'Throttle', key: 'vfr', value: (d) => fmt(d.throttle, 0, '%') },
  {
    label: 'Battery', key: 'battery', value: (d) => fmt(d.voltage, 2, 'V'),
    detail: (d) => `${isNum(d.remaining) ? `${d.remaining} %` : DASH} · ${fmt(d.current, 1, 'A')}`,
    warn: (d) => isNum(d.remaining) && d.remaining < 20,
  },
  {
    label: 'GPS', key: 'gps', value: (d) => gpsFixName(d.fixType),
    detail: (d) => `${isNum(d.satellites) ? d.satellites : DASH} sats · HDOP ${fmt(d.eph, 1)}`,
    warn: (d) => !isNum(d.fixType) || d.fixType < 3,
  },
  { label: 'Mode', key: 'heartbeat', value: (d) => (typeof d.mode === 'string' ? d.mode : DASH) },
  {
    label: 'Arming', key: 'heartbeat', value: (d) => (d.armed === true ? 'ARMED' : d.armed === false ? 'Disarmed' : DASH),
    warn: (d) => d.armed === true,
  },
];

interface TileNodes {
  spec: TileSpec;
  root: HTMLElement;
  value: HTMLElement;
  detail: HTMLElement;
}

export class HudTiles {
  readonly root = el('div', { className: 'hud-tiles' });
  private readonly tiles: TileNodes[];

  constructor(private readonly state: WebviewState) {
    this.tiles = TILES.map((spec) => {
      const value = el('div', { className: 'tile-value', text: DASH });
      const detail = el('div', { className: 'tile-detail' });
      const root = el('div', { className: 'tile' }, el('div', { className: 'tile-label', text: spec.label }), value, detail);
      this.root.appendChild(root);
      return { spec, root, value, detail };
    });
  }

  render(): void {
    for (const tile of this.tiles) {
      const data = this.state.value(tile.spec.key);
      setText(tile.value, data ? tile.spec.value(data) : DASH);
      setText(tile.detail, data && tile.spec.detail ? tile.spec.detail(data) : '');
      tile.root.classList.toggle('stale', this.state.isStale(tile.spec.key));
      tile.root.classList.toggle('warn', Boolean(data && tile.spec.warn?.(data)));
    }
  }
}
