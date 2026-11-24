// The three states every tab has: disconnected (with Quick Connect), waiting
// for data, and live (banner hidden, content shown).
import { button, el, setText } from './dom-helpers';
import { postToHost } from './webview-state';

export type TabPhase = 'disconnected' | 'waiting' | 'live';

export class TabStateBanner {
  readonly root = el('div', { className: 'tab-banner' });
  private readonly message = el('p', { className: 'tab-banner-text' });
  private readonly connect = button('Quick Connect', () => postToHost({ type: 'run', command: 'quickConnect' }),
    { className: 'primary' });
  phase: TabPhase | undefined;

  constructor(private readonly waitingText: string) {
    this.root.append(this.message, this.connect);
  }

  /** Show the banner for a phase; `content` is hidden unless the phase is live. */
  update(phase: TabPhase, content?: HTMLElement): void {
    if (content) content.hidden = phase !== 'live';
    if (this.phase === phase) return;
    this.phase = phase;
    this.root.hidden = phase === 'live';
    this.connect.hidden = phase !== 'disconnected';
    setText(this.message, phase === 'disconnected' ? 'No vehicle connected.' : this.waitingText);
  }
}
