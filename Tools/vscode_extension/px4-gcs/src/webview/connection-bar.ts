// Top bar: link state, transport, port and baud, Quick Connect / Connect /
// Disconnect, and the .tlog record toggle. State and arming changes are
// announced through a live region.
import { DashboardConnection, LinkSummary } from '../dashboard/dashboard-messages';
import { button, el, setText, stateDot } from './dom-helpers';
import { postToHost, WebviewState } from './webview-state';

const STATE_TEXT: Record<DashboardConnection, string> = {
  idle: 'Disconnected', connecting: 'Connecting', connected: 'Connected', lost: 'Link lost', disconnecting: 'Disconnecting',
};

export function linkText(link: LinkSummary | null): string {
  if (!link) return '';
  const where = link.transport === 'udp' ? `UDP ${link.host ?? ''}:${link.udpPort ?? ''}`
    : `${link.port ?? 'serial'}${link.baud ? ` @ ${link.baud}` : ''}`;
  return link.systemId !== undefined ? `${where} · system ${link.systemId}` : where;
}

export class ConnectionBar {
  readonly root = el('header', { className: 'connection-bar' });
  private readonly dotSlot = el('span', { className: 'dot-slot' });
  private readonly stateLabel = el('strong', { className: 'conn-state' });
  private readonly linkLabel = el('span', { className: 'conn-link' });
  private readonly armedLabel = el('span', { className: 'conn-armed' });
  private readonly announcer = el('div', { className: 'sr-only', attrs: { 'aria-live': 'polite', role: 'status' } });
  private readonly quick = button('Quick Connect', () => postToHost({ type: 'run', command: 'quickConnect' }), { className: 'primary' });
  private readonly pick = button('Connect…', () => postToHost({ type: 'run', command: 'connect' }));
  private readonly drop = button('Disconnect', () => postToHost({ type: 'run', command: 'disconnect' }));
  private readonly record = button('Record', () => postToHost({ type: 'run',
    command: this.state.recording.active ? 'stopRecording' : 'startRecording' }), { className: 'record' });
  private lastAnnounced = '';

  constructor(private readonly state: WebviewState) {
    this.root.append(this.dotSlot, this.stateLabel, this.linkLabel, this.armedLabel,
      el('span', { className: 'spacer' }), this.record, this.quick, this.pick, this.drop, this.announcer);
  }

  render(): void {
    const { connection } = this.state;
    const kind = connection === 'connected' ? 'ok' : connection === 'lost' ? 'error' : connection === 'idle' ? 'idle' : 'warn';
    if (this.dotSlot.dataset.kind !== kind) {
      this.dotSlot.dataset.kind = kind;
      this.dotSlot.replaceChildren(stateDot(kind));
    }
    setText(this.stateLabel, STATE_TEXT[connection]);
    setText(this.linkLabel, linkText(this.state.link));
    const heartbeat = this.state.value<{ armed?: boolean; mode?: string }>('heartbeat');
    const armed = this.state.connected && heartbeat ? (heartbeat.armed ? 'ARMED' : 'Disarmed') : '';
    setText(this.armedLabel, armed);
    this.armedLabel.classList.toggle('armed', heartbeat?.armed === true);
    const idle = connection === 'idle';
    this.quick.hidden = !idle;
    this.pick.hidden = !idle;
    this.drop.hidden = idle;
    const recording = this.state.recording.active;
    this.record.hidden = connection !== 'connected' && !recording;
    setText(this.record, recording ? 'Stop Recording' : 'Record');
    this.record.classList.toggle('recording', recording);
    this.record.title = recording ? `Recording to ${this.state.recording.path ?? ''}` : 'Record this session to a .tlog file';
    const announce = [STATE_TEXT[connection], armed].filter(Boolean).join(', ');
    if (announce !== this.lastAnnounced) {
      this.lastAnnounced = announce;
      setText(this.announcer, announce);
    }
  }
}
