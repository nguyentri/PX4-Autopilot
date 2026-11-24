// Fly tab control row: Arm, Disarm, flight mode and Reboot. The buttons only
// post a request; the host checks, shows the modal, sends and answers with the
// outcome, which appears in the status line here.
import { button, clear, el, setText } from '../dom-helpers';
import { postToHost, WebviewState } from '../webview-state';

export const UNAVAILABLE = 'not available on this vehicle';

export class ControlBar {
  readonly root = el('div', { className: 'control-bar', attrs: { role: 'group', 'aria-label': 'Vehicle control' } });
  private readonly arm = button('Arm', () => postToHost({ type: 'command', action: 'arm' }), { className: 'danger' });
  private readonly disarm = button('Disarm', () => postToHost({ type: 'command', action: 'disarm' }));
  private readonly mode = el('select', { attrs: { 'aria-label': 'Flight mode' } });
  private readonly setMode = button('Change mode', () => {
    if (this.mode.value) postToHost({ type: 'command', action: 'set_mode', mode: this.mode.value });
  });
  private readonly reboot = button('Reboot', () => postToHost({ type: 'command', action: 'reboot' }));
  private readonly outcome = el('span', { className: 'control-outcome', attrs: { role: 'status', 'aria-live': 'polite' } });
  private modesKey = '';

  constructor(private readonly state: WebviewState) {
    this.root.append(this.arm, this.disarm, this.mode, this.setMode, this.reboot, this.outcome);
  }

  render(): void {
    const { state } = this;
    const usable = state.connection === 'connected' && state.controlEnabled;
    for (const node of [this.arm, this.disarm, this.mode, this.setMode, this.reboot]) node.disabled = !usable;
    this.root.title = state.controlEnabled ? '' : 'Vehicle control is off (setting px4Gcs.control.enabled).';
    const available = state.availableModes();
    const current = state.value<{ modeKey?: string | null }>('heartbeat')?.modeKey ?? '';
    const key = JSON.stringify([state.modes.map((m) => m.key), available, current]);
    if (key !== this.modesKey) {
      this.modesKey = key;
      const selected = this.mode.value || current;
      clear(this.mode);
      for (const mode of state.modes) {
        const missing = available !== null && !available.includes(mode.key);
        const label = `${mode.name}${mode.key === current ? ' (current)' : ''}${missing ? ` (${UNAVAILABLE})` : ''}`;
        const option = el('option', { text: label, attrs: { value: mode.key } });
        option.disabled = missing;
        this.mode.appendChild(option);
      }
      if (selected) this.mode.value = selected;
    }
    const outcome = state.commandOutcome;
    setText(this.outcome, outcome ? outcome.message : '');
    this.outcome.className = `control-outcome${outcome && outcome.result !== 'accepted' ? ' warn' : ''}`;
  }
}
