// Draws the track on a 2D canvas: metre grid, track line, home marker, vehicle
// with heading, north arrow and scale bar. Colours come from the VS Code theme
// variables so the drawing follows light, dark and high-contrast themes.
import { el } from '../dom-helpers';
import { EastNorth, scaleBar, toScreen, Track, TrackView } from './track-projection';

const SCALE_MAX_PX = 120;

interface Palette {
  fg: string;
  muted: string;
  grid: string;
  track: string;
  vehicle: string;
  home: string;
}

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function palette(): Palette {
  return {
    fg: cssVar('--vscode-foreground', '#cccccc'),
    muted: cssVar('--vscode-descriptionForeground', '#888888'),
    grid: cssVar('--vscode-panel-border', 'rgba(128,128,128,0.35)'),
    track: cssVar('--vscode-charts-blue', '#3794ff'),
    vehicle: '#ED6C00',
    home: cssVar('--vscode-charts-green', '#3fb950'),
  };
}

export class TrackCanvas {
  readonly root = el('canvas', { className: 'track-canvas', attrs: { role: 'img', 'aria-label': 'Vehicle track' } });

  /** CSS pixel size of the drawing area. */
  size(): { width: number; height: number } {
    return { width: this.root.clientWidth, height: this.root.clientHeight };
  }

  draw(view: TrackView, track: Track, vehicle: EastNorth | undefined, headingDeg: number | undefined): void {
    const { width, height } = this.size();
    if (width === 0 || height === 0) return;
    const ratio = window.devicePixelRatio || 1;
    if (this.root.width !== Math.round(width * ratio) || this.root.height !== Math.round(height * ratio)) {
      this.root.width = Math.round(width * ratio);
      this.root.height = Math.round(height * ratio);
    }
    const ctx = this.root.getContext('2d');
    if (!ctx) return;
    const colors = palette();
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const bar = scaleBar(view.metersPerPixel, SCALE_MAX_PX);
    this.grid(ctx, view, { width, height }, bar.meters, colors.grid);
    this.line(ctx, view, { width, height }, track.points, colors.track);
    this.home(ctx, toScreen(view, { width, height }, { east: 0, north: 0 }), colors.home);
    if (vehicle) this.vehicle(ctx, toScreen(view, { width, height }, vehicle), headingDeg, colors.vehicle);
    this.north(ctx, width, colors.fg);
    this.scale(ctx, height, bar.pixels, bar.label, colors.fg);
  }

  private grid(ctx: CanvasRenderingContext2D, view: TrackView, size: { width: number; height: number }, step: number,
    color: string): void {
    const halfW = (size.width / 2) * view.metersPerPixel;
    const halfH = (size.height / 2) * view.metersPerPixel;
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let e = Math.ceil((view.center.east - halfW) / step) * step; e <= view.center.east + halfW; e += step) {
      const { x } = toScreen(view, size, { east: e, north: 0 });
      ctx.moveTo(Math.round(x) + 0.5, 0);
      ctx.lineTo(Math.round(x) + 0.5, size.height);
    }
    for (let n = Math.ceil((view.center.north - halfH) / step) * step; n <= view.center.north + halfH; n += step) {
      const { y } = toScreen(view, size, { east: 0, north: n });
      ctx.moveTo(0, Math.round(y) + 0.5);
      ctx.lineTo(size.width, Math.round(y) + 0.5);
    }
    ctx.stroke();
  }

  private line(ctx: CanvasRenderingContext2D, view: TrackView, size: { width: number; height: number },
    points: readonly EastNorth[], color: string): void {
    if (points.length < 2) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    points.forEach((p, i) => {
      const { x, y } = toScreen(view, size, p);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  private home(ctx: CanvasRenderingContext2D, at: { x: number; y: number }, color: string): void {
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(at.x, at.y, 7, 0, Math.PI * 2);
    ctx.stroke();
    ctx.font = 'bold 9px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('H', at.x, at.y + 0.5);
  }

  private vehicle(ctx: CanvasRenderingContext2D, at: { x: number; y: number }, headingDeg: number | undefined,
    color: string): void {
    ctx.save();
    ctx.translate(at.x, at.y);
    ctx.fillStyle = color;
    ctx.strokeStyle = '#16163F';
    ctx.lineWidth = 1;
    ctx.beginPath();
    if (headingDeg === undefined) {
      ctx.arc(0, 0, 6, 0, Math.PI * 2);
    } else {
      ctx.rotate((headingDeg * Math.PI) / 180);
      ctx.moveTo(0, -11);
      ctx.lineTo(7, 8);
      ctx.lineTo(0, 4);
      ctx.lineTo(-7, 8);
      ctx.closePath();
    }
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  private north(ctx: CanvasRenderingContext2D, width: number, color: string): void {
    const x = width - 22;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, 12);
    ctx.lineTo(x + 6, 30);
    ctx.lineTo(x, 26);
    ctx.lineTo(x - 6, 30);
    ctx.closePath();
    ctx.fill();
    ctx.font = 'bold 11px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText('N', x, 33);
  }

  private scale(ctx: CanvasRenderingContext2D, height: number, pixels: number, label: string, color: string): void {
    const y = height - 14;
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(12, y - 5);
    ctx.lineTo(12, y);
    ctx.lineTo(12 + pixels, y);
    ctx.lineTo(12 + pixels, y - 5);
    ctx.stroke();
    ctx.font = '11px sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'bottom';
    ctx.fillText(label, 16, y - 4);
  }
}
