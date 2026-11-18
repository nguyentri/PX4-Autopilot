// Compass tape: ticks every 10 degrees across a 90 degree window, cardinal
// letters at N/E/S/W and numbers every 30 degrees.
import { clear, svg } from '../dom-helpers';
import { wrap180, wrap360 } from '../format/telemetry-format';

export interface HeadingTick {
  deg: number;
  /** Signed offset from the current heading in degrees. */
  offset: number;
  label: string | null;
}

const CARDINAL: Record<number, string> = { 0: 'N', 90: 'E', 180: 'S', 270: 'W' };

export function headingTicks(heading: number, span = 90, step = 10): HeadingTick[] {
  const ticks: HeadingTick[] = [];
  const centre = wrap360(heading);
  const first = Math.ceil((centre - span / 2) / step) * step;
  for (let raw = first; raw <= centre + span / 2; raw += step) {
    const deg = wrap360(raw);
    const offset = wrap180(raw - centre);
    ticks.push({ deg, offset, label: CARDINAL[deg] ?? (deg % 30 === 0 ? String(deg) : null) });
  }
  return ticks;
}

const WIDTH = 300;
const SPAN = 90;

export class HeadingTape {
  private readonly ticks = svg('g');
  private readonly readout = svg('text', { x: WIDTH / 2, y: 44, class: 'heading-readout' });
  readonly root = svg('svg', { viewBox: `0 0 ${WIDTH} 50`, class: 'heading-tape', role: 'img', 'aria-label': 'Heading' },
    this.ticks, svg('path', { d: `M ${WIDTH / 2 - 6} 0 L ${WIDTH / 2 + 6} 0 L ${WIDTH / 2} 8 Z`, class: 'heading-pointer' }),
    this.readout);
  private shown: number | undefined;

  frame(heading: number | undefined): void {
    if (heading === undefined) return;
    const rounded = Math.round(wrap360(heading));
    if (rounded === this.shown) return;
    this.shown = rounded;
    clear(this.ticks);
    for (const tick of headingTicks(rounded, SPAN)) {
      const x = WIDTH / 2 + (tick.offset * WIDTH) / SPAN;
      this.ticks.appendChild(svg('line', { x1: x, y1: 10, x2: x, y2: tick.label ? 22 : 16, class: 'heading-tick' }));
      if (tick.label) this.ticks.appendChild(svg('text', { x, y: 32, class: 'heading-label' }, tick.label));
    }
    this.readout.textContent = `${String(rounded).padStart(3, '0')}°`;
  }
}
