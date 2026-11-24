// Fly tab: control row, attitude indicator, heading tape, tiles and the status log. The
// instruments redraw on animation frames from the latest values.
import { el } from '../dom-helpers';
import { TabStateBanner } from '../tab-state-banner';
import { TabView } from '../tab-router';
import { WebviewState } from '../webview-state';
import { AttitudeIndicator } from './attitude-indicator';
import { ControlBar } from './control-bar';
import { HeadingTape } from './heading-tape';
import { HudTiles } from './hud-tiles';
import { StatusLog } from './status-log';

export class FlyTab implements TabView {
  readonly root = el('div', { className: 'fly-tab' });
  readonly status = new StatusLog();
  private readonly control: ControlBar;
  private readonly banner = new TabStateBanner('Waiting for attitude and position data…');
  private readonly adi = new AttitudeIndicator();
  private readonly tape = new HeadingTape();
  private readonly tiles: HudTiles;
  private readonly instruments = el('div', { className: 'instruments' });

  constructor(private readonly state: WebviewState) {
    this.tiles = new HudTiles(state);
    this.control = new ControlBar(state);
    this.instruments.append(el('div', { className: 'adi-wrap' }, this.adi.root, this.tape.root), this.tiles.root);
    this.root.append(this.control.root, this.banner.root, this.instruments, this.status.root);
  }

  /** Called on each animation frame while the tab is visible. */
  frame(): void {
    const state = this.state;
    this.banner.update(!state.connected ? 'disconnected' : state.value('heartbeat') ? 'live' : 'waiting', this.instruments);
    const attitude = state.value<{ roll?: number; pitch?: number; yaw?: number }>('attitude');
    this.adi.frame(attitude?.roll, attitude?.pitch);
    this.adi.root.classList.toggle('stale', state.isStale('attitude'));
    const vfr = state.value<{ heading?: number }>('vfr');
    const heading = vfr?.heading ?? (attitude?.yaw !== undefined ? (attitude.yaw * 180) / Math.PI : undefined);
    this.tape.frame(heading);
    this.tiles.render();
    this.control.render();
  }
}
