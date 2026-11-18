// Sensor Bench: IMU, magnetometer, barometer, distance and GPS cards plus the
// NAMED_VALUE table (ADC channels such as ADS_A0..A3). While visible, the host
// raises HIGHRES_IMU, SCALED_PRESSURE and DISTANCE_SENSOR rates; a refused
// request shows on the card instead of failing silently.
import { el, setText } from '../dom-helpers';
import { ageText, DASH, fmt, gpsFixName, isNum, vec3 } from '../format/telemetry-format';
import { TabStateBanner } from '../tab-state-banner';
import { TabView } from '../tab-router';
import { WebviewState } from '../webview-state';
import { SensorCard } from './sensor-card';

/** MAVLink message id raised by the host for each card. */
export const CARD_MESSAGE: Record<number, string> = { 105: 'imu', 29: 'baro', 132: 'distance' };

export function streamNoteText(outcome: 'raised' | 'refused', reason?: string): string | null {
  return outcome === 'refused' ? `Rate not raised${reason ? `: ${reason}` : ''}. Showing the vehicle's default rate.` : null;
}

const ORIENTATION: Record<number, string> = { 0: 'forward', 4: 'back', 24: 'up', 25: 'down' };

export class SensorBench implements TabView {
  readonly root = el('div', { className: 'sensors-tab' });
  private readonly banner = new TabStateBanner('Waiting for sensor data…');
  private readonly grid = el('div', { className: 'sensor-grid' });
  private readonly namedBody = el('tbody');
  private readonly content = el('div');
  private readonly cards: Record<string, SensorCard> = {
    imu: new SensorCard('IMU', 'sensors:imu', [
      { label: 'Accel (m/s²)', value: (d) => vec3(d.accel, 2) },
      { label: 'Gyro (rad/s)', value: (d) => vec3(d.gyro, 3) },
      { label: 'Temperature', value: (d) => fmt(d.temperature, 1, '°C') },
    ]),
    mag: new SensorCard('Magnetometer', 'sensors:imu', [
      { label: 'Field (gauss)', value: (d) => vec3(d.mag, 3) },
      { label: 'Magnitude', value: (d) => magnitude(d.mag) },
    ]),
    baro: new SensorCard('Barometer', 'sensors:baro', [
      { label: 'Pressure', value: (d) => fmt(d.pressure, 2, 'hPa') },
      { label: 'Altitude', value: (d) => fmt(d.altitude, 2, 'm') },
      { label: 'Temperature', value: (d) => fmt(d.temperature, 1, '°C') },
    ]),
    distance: new SensorCard('Distance', 'sensors:distance', [
      { label: 'Range', value: (d) => fmt(d.current, 2, 'm') },
      { label: 'Limits', value: (d) => (isNum(d.min) && isNum(d.max) ? `${fmt(d.min, 2)}–${fmt(d.max, 2)} m` : DASH) },
      { label: 'Facing', value: (d) => (isNum(d.orientation) ? ORIENTATION[d.orientation] ?? `#${d.orientation}` : DASH) },
    ]),
    gps: new SensorCard('GPS', 'gps', [
      { label: 'Fix', value: (d) => gpsFixName(d.fixType) },
      { label: 'Satellites', value: (d) => (isNum(d.satellites) ? String(d.satellites) : DASH) },
      { label: 'Position', value: (d) => (isNum(d.lat) && isNum(d.lon) ? `${d.lat.toFixed(7)}, ${d.lon.toFixed(7)}` : DASH) },
      { label: 'HDOP / VDOP', value: (d) => `${fmt(d.eph, 2)} / ${fmt(d.epv, 2)}` },
    ]),
  };
  private readonly namedRows = new Map<string, { value: HTMLElement; age: HTMLElement; row: HTMLElement }>();

  constructor(private readonly state: WebviewState) {
    for (const card of Object.values(this.cards)) this.grid.appendChild(card.root);
    const table = el('table', { className: 'named-table' },
      el('caption', { text: 'Named values' }),
      el('thead', {}, el('tr', {}, el('th', { text: 'Name' }), el('th', { text: 'Value' }), el('th', { text: 'Age' }))),
      this.namedBody);
    this.content.append(this.grid, table);
    this.root.append(this.banner.root, this.content);
  }

  streamNote(message: number, outcome: 'raised' | 'refused', reason?: string): void {
    const card = CARD_MESSAGE[message];
    if (card) this.cards[card].setNote(streamNoteText(outcome, reason));
  }

  frame(): void {
    const state = this.state;
    const any = ['sensors:imu', 'sensors:baro', 'sensors:distance', 'gps'].some((k) => state.values.has(k))
      || state.keys('named_value:').length > 0;
    this.banner.update(!state.connected ? 'disconnected' : any ? 'live' : 'waiting', this.content);
    for (const card of Object.values(this.cards)) card.render(state);
    for (const key of state.keys('named_value:')) {
      let nodes = this.namedRows.get(key);
      if (!nodes) {
        const value = el('td');
        const age = el('td');
        const row = el('tr', {}, el('td', { text: key.slice('named_value:'.length) }), value, age);
        nodes = { value, age, row };
        this.namedRows.set(key, nodes);
        this.namedBody.appendChild(row);
      }
      const data = state.value<{ value?: number }>(key);
      setText(nodes.value, fmt(data?.value, 4));
      setText(nodes.age, ageText(state.ageMs(key) ?? NaN));
      nodes.row.classList.toggle('stale', state.isStale(key));
    }
  }
}

function magnitude(value: unknown): string {
  if (!Array.isArray(value) || value.length < 3 || !value.every(isNum)) return DASH;
  return fmt(Math.hypot(value[0], value[1], value[2]), 3, 'G');
}
