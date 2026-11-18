import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';

export type PaneCore = 'cr8_0' | 'cr8_1';
export type PostMessage = (message: Record<string, unknown>) => void;

export const CORE_NAMES: Record<PaneCore, string> = { cr8_0: 'R8-0', cr8_1: 'R8-1' };

export function css(name: string, fallback: string): string {
  return getComputedStyle(document.body).getPropertyValue(name).trim() || fallback;
}

/** xterm colours follow the VS Code terminal theme, including high contrast. */
export function theme(): Record<string, string> {
  const background = css('--vscode-terminal-background', css('--vscode-panel-background', '#1e1e1e'));
  return {
    background, foreground: css('--vscode-terminal-foreground', css('--vscode-foreground', '#cccccc')),
    cursor: css('--vscode-terminalCursor-foreground', css('--vscode-foreground', '#cccccc')),
    selectionBackground: css('--vscode-terminal-selectionBackground', '#264f78'),
  };
}

export function button(label: string, aria: string, onClick: () => void): HTMLButtonElement {
  const element = document.createElement('button');
  element.type = 'button';
  element.textContent = label;
  element.setAttribute('aria-label', aria);
  element.title = aria;
  element.addEventListener('click', onClick);
  return element;
}

/**
 * One core's trace pane: a status badge, a terminal, and its own input line
 * and tools, so in the split layout each core is driven from its own pane.
 */
export class TracePane {
  public readonly element = document.createElement('section');
  private readonly badge = document.createElement('span');
  private readonly terminal: Terminal;
  private readonly fit = new FitAddon();
  private readonly history: string[] = [];
  private historyIndex = 0;

  constructor(public readonly core: PaneCore, post: PostMessage) {
    const name = CORE_NAMES[core];
    this.element.className = 'pane';
    this.element.setAttribute('aria-label', `${name} trace`);
    const header = document.createElement('div');
    header.className = 'bar';
    const title = document.createElement('strong');
    title.className = 'pane-title';
    title.textContent = name;
    this.badge.className = 'badge';
    this.badge.setAttribute('role', 'status');
    this.badge.setAttribute('aria-live', 'polite');
    this.badge.textContent = 'Stopped';
    header.append(title, this.badge);

    const screen = document.createElement('div');
    screen.className = 'screen';
    const footer = document.createElement('form');
    footer.className = 'bar';
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = `NSH command for ${name}, Enter to send`;
    input.setAttribute('aria-label', `Line to send to ${name}`);
    input.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') { return; }
      event.preventDefault();
      this.historyIndex = Math.max(0, Math.min(this.history.length, this.historyIndex + (event.key === 'ArrowUp' ? -1 : 1)));
      input.value = this.history[this.historyIndex] || '';
    });
    const send = button('Send', `Send the line to ${name}`, () => undefined);
    send.type = 'submit';
    footer.append(input, send,
      button('Clear', `Clear the ${name} trace`, () => post({ type: 'clear', core })),
      button('Copy', `Copy the selection, or the whole ${name} trace`, () => post({ type: 'copy', core, text: this.terminal.getSelection() })),
      button('Save Log', `Save the ${name} trace under logs/rtt/`, () => post({ type: 'save', core })));
    footer.addEventListener('submit', (event) => {
      event.preventDefault();
      if (input.value) { this.history.push(input.value); }
      this.historyIndex = this.history.length;
      post({ type: 'input', core, text: input.value });
      input.value = '';
    });
    this.element.addEventListener('focusin', () => post({ type: 'focus', core }));
    this.element.append(header, screen, footer);

    this.terminal = new Terminal({ convertEol: false, disableStdin: true, scrollback: 10000, fontSize: 12, theme: theme(),
      fontFamily: css('--vscode-editor-font-family', 'monospace') });
    this.terminal.loadAddon(this.fit);
    this.terminal.open(screen);
    new ResizeObserver(() => this.refit()).observe(screen);
  }

  public refit(): void { try { this.fit.fit(); } catch { /* a hidden pane has no size */ } }

  public retheme(): void { this.terminal.options.theme = theme(); }

  public reset(text: string): void { this.terminal.reset(); this.terminal.write(text); }

  public write(text: string): void { this.terminal.write(text); }

  public setState(state: string, text: string): void {
    this.badge.textContent = text;
    this.badge.dataset.state = state;
  }

  public setVisible(visible: boolean): void {
    this.element.hidden = !visible;
    if (visible) { this.refit(); }
  }
}
