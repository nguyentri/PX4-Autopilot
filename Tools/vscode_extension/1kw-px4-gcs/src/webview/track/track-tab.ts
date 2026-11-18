// Track tab: the session track on a metre grid, no map tiles. Fit shows the
// whole track, Follow keeps the vehicle centred, the wheel and the zoom
// buttons change scale and dragging pans (which stops following). Distance
// and bearing from home are also given as text for screen readers.
import { button, el, setText } from '../dom-helpers';
import { fmt } from '../format/telemetry-format';
import { TabStateBanner } from '../tab-state-banner';
import { TabView } from '../tab-router';
import { postToHost, WebviewState } from '../webview-state';
import { TrackCanvas } from './track-canvas';
import {
  buildTrack, distanceBearing, EastNorth, fitView, NO_POSITION_TEXT, Track, TrackView,
} from './track-projection';

const ZOOM_STEP = 1.5;
const MIN_MPP = 0.01;
const MAX_MPP = 2000;

export function trackSummary(track: Track): string {
  return track.source === 'local' ? 'Local NED from LOCAL_POSITION_NED, home is the estimator origin.'
    : `GPS from GLOBAL_POSITION_INT, home is the session's first fix (${track.home?.lat.toFixed(7)}, `
      + `${track.home?.lon.toFixed(7)}).`;
}

export function homeText(vehicle: EastNorth | undefined): string {
  if (!vehicle) return 'No position yet.';
  const { distance, bearing } = distanceBearing({ east: 0, north: 0 }, vehicle);
  return `From home: ${fmt(distance, 1, 'm')}, bearing ${String(Math.round(bearing) % 360).padStart(3, '0')}°`;
}

export class TrackTab implements TabView {
  readonly root = el('div', { className: 'track-tab' });
  private readonly banner = new TabStateBanner(NO_POSITION_TEXT);
  private readonly canvas = new TrackCanvas();
  private readonly content = el('div', { className: 'track-content' });
  private readonly readout = el('p', { className: 'track-readout', attrs: { 'aria-live': 'polite' } });
  private readonly source = el('p', { className: 'track-source' });
  private readonly followBox = el('input', { attrs: { type: 'checkbox', id: 'track-follow' } });
  private view: TrackView | undefined;
  private follow = true;
  private requested = false;
  private drawn = '';
  private drag: { x: number; y: number; view: TrackView } | undefined;
  private track: Track | undefined;

  constructor(private readonly state: WebviewState) {
    this.followBox.checked = true;
    this.followBox.addEventListener('change', () => {
      this.follow = this.followBox.checked;
      this.redraw();
    });
    const tools = el('div', { className: 'track-tools' },
      button('Fit', () => this.fit()),
      button('+', () => this.zoom(1 / ZOOM_STEP), { title: 'Zoom in', attrs: { 'aria-label': 'Zoom in' } }),
      button('−', () => this.zoom(ZOOM_STEP), { title: 'Zoom out', attrs: { 'aria-label': 'Zoom out' } }),
      el('label', { attrs: { for: 'track-follow' } }, this.followBox, ' Follow'),
      this.readout);
    this.content.append(tools, this.canvas.root, this.source);
    this.root.append(this.banner.root, this.content);
    this.bindPointer();
  }

  show(visible: boolean): void {
    if (!visible) return;
    this.drawn = '';
    if (!this.requested && !this.state.history.seeded) {
      this.requested = true;
      postToHost({ type: 'history_request' });
    }
  }

  frame(): void {
    const history = this.state.history;
    this.track = buildTrack(history.get('local_position'), history.get('position'));
    const track = this.track;
    this.banner.update(track ? 'live' : this.state.connected ? 'waiting' : 'disconnected', this.content);
    if (!track) return;
    const size = this.canvas.size();
    if (size.width === 0 || size.height === 0) return; // not laid out yet: an initial fit would pick a wild scale
    const key = `${history.version}:${size.width}x${size.height}:${this.follow}:${this.view?.metersPerPixel}:${this.view?.center.east}:${this.view?.center.north}`;
    if (key === this.drawn) return;
    this.drawn = key;
    const vehicle = track.points[track.points.length - 1];
    if (!this.view) this.view = fitView([{ east: 0, north: 0 }, ...track.points], size);
    if (this.follow && vehicle) this.view = { ...this.view, center: { east: vehicle.east, north: vehicle.north } };
    this.canvas.draw(this.view, track, vehicle, this.heading());
    setText(this.readout, homeText(vehicle));
    setText(this.source, `${trackSummary(track)} ${track.points.length} points.`);
  }

  /** Vehicle heading in degrees: attitude yaw, else the GLOBAL_POSITION_INT heading. */
  private heading(): number | undefined {
    const yaw = this.state.value<{ yaw?: unknown }>('attitude')?.yaw;
    if (typeof yaw === 'number' && Number.isFinite(yaw)) return (yaw * 180) / Math.PI;
    const heading = this.state.value<{ heading?: unknown }>('position')?.heading;
    return typeof heading === 'number' && Number.isFinite(heading) ? heading : undefined;
  }

  private redraw(): void {
    this.drawn = '';
    this.frame();
  }

  private fit(): void {
    if (!this.track) return;
    this.setFollow(false);
    this.view = fitView([{ east: 0, north: 0 }, ...this.track.points], this.canvas.size());
    this.redraw();
  }

  private zoom(factor: number): void {
    if (!this.view) return;
    const metersPerPixel = Math.min(MAX_MPP, Math.max(MIN_MPP, this.view.metersPerPixel * factor));
    this.view = { ...this.view, metersPerPixel };
    this.redraw();
  }

  private setFollow(on: boolean): void {
    this.follow = on;
    this.followBox.checked = on;
  }

  private bindPointer(): void {
    const canvas = this.canvas.root;
    canvas.addEventListener('wheel', (event) => {
      event.preventDefault();
      this.zoom(event.deltaY > 0 ? ZOOM_STEP : 1 / ZOOM_STEP);
    }, { passive: false });
    canvas.addEventListener('pointerdown', (event) => {
      if (!this.view) return;
      this.drag = { x: event.clientX, y: event.clientY, view: this.view };
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointermove', (event) => {
      if (!this.drag) return;
      const { x, y, view } = this.drag;
      if (Math.abs(event.clientX - x) + Math.abs(event.clientY - y) > 2) this.setFollow(false);
      if (this.follow) return;
      this.view = {
        metersPerPixel: view.metersPerPixel,
        center: {
          east: view.center.east - (event.clientX - x) * view.metersPerPixel,
          north: view.center.north + (event.clientY - y) * view.metersPerPixel,
        },
      };
      this.redraw();
    });
    const end = (): void => { this.drag = undefined; };
    canvas.addEventListener('pointerup', end);
    canvas.addEventListener('pointercancel', end);
  }
}
