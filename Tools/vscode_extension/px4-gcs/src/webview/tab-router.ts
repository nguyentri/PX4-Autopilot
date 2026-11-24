// Keyboard-navigable tab strip (WAI-ARIA tabs pattern): arrow keys, Home and
// End move focus and select; only the selected panel is in the page flow.
import { TAB_IDS, TabId } from '../dashboard/dashboard-messages';
import { el } from './dom-helpers';

export const TAB_LABELS: Record<TabId, string> = {
  fly: 'Fly', parameters: 'Parameters', console: 'Console', inspector: 'Inspector', sensors: 'Sensors',
  plots: 'Plots', track: 'Track', logs: 'Logs',
};

export interface TabView {
  root: HTMLElement;
  /** Called when the tab becomes selected or leaves. */
  show?(visible: boolean): void;
}

export class TabRouter {
  readonly strip = el('div', { className: 'tab-strip', attrs: { role: 'tablist', 'aria-label': 'Dashboard views' } });
  readonly body = el('div', { className: 'tab-body' });
  private readonly buttons = new Map<TabId, HTMLButtonElement>();
  private readonly panels = new Map<TabId, HTMLElement>();
  private current: TabId | undefined;

  constructor(private readonly views: Record<TabId, TabView>, private readonly onSelect: (tab: TabId) => void) {
    for (const id of TAB_IDS) {
      const tab = el('button', {
        className: 'tab', text: TAB_LABELS[id],
        attrs: { type: 'button', role: 'tab', id: `tab-${id}`, 'aria-controls': `panel-${id}`, 'aria-selected': 'false', tabindex: '-1' },
      });
      tab.addEventListener('click', () => this.select(id));
      tab.addEventListener('keydown', (event) => this.onKey(event, id));
      this.buttons.set(id, tab);
      this.strip.appendChild(tab);
      const panel = el('section', {
        className: 'tab-panel', attrs: { role: 'tabpanel', id: `panel-${id}`, 'aria-labelledby': `tab-${id}` },
      }, views[id].root);
      panel.hidden = true;
      this.panels.set(id, panel);
      this.body.appendChild(panel);
    }
  }

  get selected(): TabId | undefined {
    return this.current;
  }

  select(id: TabId, notify = true): void {
    if (this.current === id) return;
    const previous = this.current;
    this.current = id;
    for (const [tab, buttonNode] of this.buttons) {
      const on = tab === id;
      buttonNode.setAttribute('aria-selected', String(on));
      buttonNode.setAttribute('tabindex', on ? '0' : '-1');
      (this.panels.get(tab) as HTMLElement).hidden = !on;
    }
    if (previous) this.views[previous].show?.(false);
    this.views[id].show?.(true);
    if (notify) this.onSelect(id);
  }

  private onKey(event: KeyboardEvent, id: TabId): void {
    const index = TAB_IDS.indexOf(id);
    const moves: Record<string, number> = {
      ArrowRight: (index + 1) % TAB_IDS.length,
      ArrowLeft: (index - 1 + TAB_IDS.length) % TAB_IDS.length,
      Home: 0,
      End: TAB_IDS.length - 1,
    };
    const target = moves[event.key];
    if (target === undefined) return;
    event.preventDefault();
    const next = TAB_IDS[target];
    this.select(next);
    this.buttons.get(next)?.focus();
  }
}
