// Console tab: xterm on the NSH shell. The host owns the shell, the warning
// and the journal; this tab only shows output and forwards typed bytes.
// Multi-line pastes wait for an explicit Send.
import { FitAddon } from '@xterm/addon-fit';
import { Terminal } from '@xterm/xterm';
import { button, el, setText } from '../dom-helpers';
import { TabStateBanner } from '../tab-state-banner';
import { TabView } from '../tab-router';
import { postToHost, WebviewState } from '../webview-state';
import { pasteLineCount, pasteToShell } from './console-paste-guard';

export class ConsoleTab implements TabView {
  readonly root = el('div', { className: 'console-tab' });
  private readonly banner = new TabStateBanner('The console is closed.');
  private readonly notice = el('p', { className: 'console-notice', attrs: { role: 'status' } });
  private readonly openButton = button('Open Console', () => postToHost({ type: 'console_open' }), { className: 'primary' });
  private readonly pasteBar = el('div', { className: 'paste-bar', attrs: { role: 'alert' } });
  private readonly pasteText = el('span');
  private readonly host = el('div', { className: 'terminal-host' });
  private readonly content = el('div', { className: 'console-content' });
  private terminal: Terminal | undefined;
  private fit: FitAddon | undefined;
  private pending = '';
  private visible = false;

  constructor(private readonly state: WebviewState) {
    this.pasteBar.append(this.pasteText,
      button('Send', () => this.resolvePaste(true), { className: 'primary' }),
      button('Cancel', () => this.resolvePaste(false)));
    this.pasteBar.hidden = true;
    this.content.append(this.pasteBar, this.host);
    this.root.append(this.banner.root, el('div', { className: 'console-closed' }, this.notice, this.openButton), this.content);
    new ResizeObserver(() => this.fitNow()).observe(this.host);
  }

  show(visible: boolean): void {
    this.visible = visible;
    if (visible && this.state.connected && this.state.console.state !== 'open') postToHost({ type: 'console_open' });
    if (!visible && this.state.console.state === 'open') postToHost({ type: 'console_close' });
    this.update();
  }

  write(text: string): void {
    this.terminal?.write(text);
  }

  update(): void {
    const { console: consoleState, connected } = this.state;
    const open = consoleState.state === 'open';
    this.banner.update(connected ? 'live' : 'disconnected');
    (this.notice.parentElement as HTMLElement).hidden = !connected || open;
    this.content.hidden = !connected || !open;
    setText(this.notice, consoleState.state === 'disabled' ? consoleState.reason
      : consoleState.state === 'declined' ? 'The console stayed closed. Open it to type commands on the vehicle.'
        : 'The console is closed.');
    this.openButton.hidden = consoleState.state === 'disabled';
    if (open && this.visible) {
      this.ensureTerminal();
      this.fitNow();
      this.terminal?.focus();
    }
  }

  private ensureTerminal(): void {
    if (this.terminal) return;
    const terminal = new Terminal({ convertEol: true, cursorBlink: true, fontSize: 13, scrollback: 5000 });
    const fit = new FitAddon();
    terminal.loadAddon(fit);
    terminal.open(this.host);
    terminal.onData((data) => postToHost({ type: 'console_input', data }));
    // Pastes arrive through the textarea; catch multi-line ones before xterm sends them.
    this.host.addEventListener('paste', (event) => {
      const text = event.clipboardData?.getData('text') ?? '';
      if (pasteLineCount(text) <= 1) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      this.pending = text;
      setText(this.pasteText, `Paste ${pasteLineCount(text)} lines into the vehicle shell? Each line runs at once.`);
      this.pasteBar.hidden = false;
    }, true);
    this.terminal = terminal;
    this.fit = fit;
  }

  private resolvePaste(send: boolean): void {
    if (send && this.pending) postToHost({ type: 'console_input', data: pasteToShell(this.pending) });
    this.pending = '';
    this.pasteBar.hidden = true;
    this.terminal?.focus();
  }

  private fitNow(): void {
    if (!this.fit || !this.visible || this.content.hidden) return;
    try {
      this.fit.fit();
    } catch {
      // The host element has no size yet (tab hidden); the next resize fits it.
    }
  }
}
