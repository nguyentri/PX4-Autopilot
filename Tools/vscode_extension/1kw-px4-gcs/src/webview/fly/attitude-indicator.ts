// SVG artificial horizon. The math is pure (tested); rendering only moves one
// group per animation frame. Easing is off under prefers-reduced-motion.
import { svg } from '../dom-helpers';
import { radToDeg } from '../format/telemetry-format';

/** Pixels per degree of pitch in the 200 x 200 view box (about ±40° visible). */
export const PX_PER_DEG = 2.5;
const EASE = 0.35;

export interface HorizonPose {
  /** Rotation of the horizon group in degrees (opposite to the vehicle roll). */
  rotateDeg: number;
  /** Downward shift of the horizon in view-box pixels (nose up moves the horizon down). */
  offsetPx: number;
}

export function horizonTransform(rollRad: number, pitchRad: number, pxPerDeg = PX_PER_DEG): HorizonPose {
  const pitch = Math.max(-90, Math.min(90, radToDeg(pitchRad)));
  return { rotateDeg: -radToDeg(rollRad), offsetPx: pitch * pxPerDeg };
}

/** One easing step toward the target, taking the short way round for the angle. */
export function easePose(from: HorizonPose, to: HorizonPose, factor = EASE): HorizonPose {
  let delta = to.rotateDeg - from.rotateDeg;
  delta = ((((delta + 180) % 360) + 360) % 360) - 180;
  return { rotateDeg: from.rotateDeg + delta * factor, offsetPx: from.offsetPx + (to.offsetPx - from.offsetPx) * factor };
}

export class AttitudeIndicator {
  readonly root: SVGSVGElement;
  private readonly horizon: SVGGElement;
  private pose: HorizonPose = { rotateDeg: 0, offsetPx: 0 };
  private readonly reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  constructor() {
    const ladder: SVGElement[] = [];
    for (let deg = -30; deg <= 30; deg += 10) {
      if (deg === 0) continue;
      const y = -deg * PX_PER_DEG;
      const half = deg % 20 === 0 ? 30 : 18;
      ladder.push(svg('line', { x1: -half, y1: y, x2: half, y2: y, class: 'ladder' }));
      ladder.push(svg('text', { x: half + 4, y: y + 4, class: 'ladder-label' }, String(Math.abs(deg))));
    }
    this.horizon = svg('g', {},
      svg('rect', { x: -400, y: -400, width: 800, height: 400, class: 'sky' }),
      svg('rect', { x: -400, y: 0, width: 800, height: 400, class: 'ground' }),
      svg('line', { x1: -400, y1: 0, x2: 400, y2: 0, class: 'horizon-line' }),
      ...ladder);
    this.root = svg('svg', { viewBox: '-100 -100 200 200', class: 'attitude', role: 'img', 'aria-label': 'Attitude indicator' },
      svg('clipPath', { id: 'adi-clip' }, svg('circle', { cx: 0, cy: 0, r: 96 })),
      svg('g', { 'clip-path': 'url(#adi-clip)' }, this.horizon),
      svg('circle', { cx: 0, cy: 0, r: 96, class: 'bezel' }),
      svg('path', { d: 'M -50 0 L -15 0 L -8 8 M 50 0 L 15 0 L 8 8', class: 'aircraft' }),
      svg('circle', { cx: 0, cy: 0, r: 2.5, class: 'aircraft-dot' }));
  }

  /** Move toward the latest attitude; call once per animation frame. */
  frame(roll: number | undefined, pitch: number | undefined): void {
    if (roll === undefined || pitch === undefined) return;
    const target = horizonTransform(roll, pitch);
    this.pose = this.reduceMotion.matches ? target : easePose(this.pose, target);
    const { rotateDeg, offsetPx } = this.pose;
    this.horizon.setAttribute('transform', `rotate(${rotateDeg.toFixed(2)}) translate(0 ${offsetPx.toFixed(2)})`);
  }
}
