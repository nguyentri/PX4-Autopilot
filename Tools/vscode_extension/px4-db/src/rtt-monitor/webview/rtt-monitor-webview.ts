import { button, CORE_NAMES, PaneCore, TracePane } from './rtt-monitor-pane';

declare function acquireVsCodeApi(): { postMessage(message: unknown): void };

type HostMessage =
  | { type: 'layout'; layout: 'single' | 'split'; shown: PaneCore }
  | { type: 'reset' | 'data'; core: PaneCore; text: string }
  | { type: 'state'; core: PaneCore; state: string; text: string; timestamps: boolean };

const vscode = acquireVsCodeApi();
const post = (message: Record<string, unknown>) => vscode.postMessage(message);

const root = document.getElementById('root')!;
const header = document.createElement('div');
header.className = 'bar';
// The core switch only exists in the single layout; the split layout shows both cores.
const cores = document.createElement('div');
cores.className = 'cores';
cores.setAttribute('role', 'radiogroup');
cores.setAttribute('aria-label', 'Core to trace');
const coreButtons = (['cr8_0', 'cr8_1'] as const).map((core) => {
  const element = button(CORE_NAMES[core], `Show the ${CORE_NAMES[core]} trace`, () => post({ type: 'switchCore', core }));
  element.setAttribute('role', 'radio');
  element.dataset.core = core;
  cores.appendChild(element);
  return element;
});
const timestamps = button('Timestamps', 'Toggle timestamps', () => post({ type: 'toggleTimestamps' }));
const spacer = document.createElement('span');
spacer.className = 'spacer';
header.append(cores, spacer, timestamps);

const panes = document.createElement('div');
panes.className = 'panes';
const paneByCore = new Map<PaneCore, TracePane>();
for (const core of ['cr8_0', 'cr8_1'] as const) {
  const pane = new TracePane(core, post);
  paneByCore.set(core, pane);
  panes.appendChild(pane.element);
}

const note = document.createElement('p');
note.className = 'note';
const notes = {
  single: 'An attached RTT bridge can briefly halt the core (stop-mode RTT); sensor timeouts under trace are bench artefacts.',
  split: 'Both consoles share one probe session over the system bus; no core is halted. Load, Recover and Debug pause both RTT panes.',
};
note.textContent = notes.single;
root.append(header, panes, note);

new MutationObserver(() => { for (const pane of paneByCore.values()) { pane.retheme(); } })
  .observe(document.body, { attributes: true, attributeFilter: ['class'] });

function setLayout(layout: 'single' | 'split', shown: PaneCore): void {
  panes.dataset.layout = layout;
  cores.hidden = layout === 'split';
  note.textContent = notes[layout];
  for (const element of coreButtons) { element.setAttribute('aria-checked', String(element.dataset.core === shown)); }
  for (const pane of paneByCore.values()) { pane.setVisible(layout === 'split' || pane.core === shown); }
}
setLayout('single', 'cr8_0');

window.addEventListener('message', (event: MessageEvent<HostMessage>) => {
  const message = event.data;
  if (message.type === 'layout') { setLayout(message.layout, message.shown); return; }
  const pane = paneByCore.get(message.core);
  if (!pane) { return; }
  if (message.type === 'reset') { pane.reset(message.text); }
  else if (message.type === 'data') { pane.write(message.text); }
  else if (message.type === 'state') {
    pane.setState(message.state, message.text);
    timestamps.setAttribute('aria-pressed', String(message.timestamps));
  }
});
post({ type: 'ready' });
