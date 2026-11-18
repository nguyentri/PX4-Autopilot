// Dashboard webview entry: builds the page, routes host messages to the tabs
// and redraws the visible tab on animation frames (Plots and Track redraw only
// when the session history changed). A one-second timer keeps
// age and stale marks moving when no new data arrives.
import { HostMessage, TAB_IDS, TabId } from '../dashboard/dashboard-messages';
import { ConnectionBar } from './connection-bar';
import { ConsoleTab } from './console/console-tab';
import { el } from './dom-helpers';
import { FlyTab } from './fly/fly-tab';
import { InspectorTab } from './inspector/inspector-tab';
import { LogsTab } from './logs/logs-tab';
import { ParameterTable } from './parameters/parameter-table';
import { PlotTab } from './plots/plot-tab';
import { SensorBench } from './sensors/sensor-bench';
import { TabRouter } from './tab-router';
import { TrackTab } from './track/track-tab';
import { postToHost, WebviewState } from './webview-state';

const state = new WebviewState();
const bar = new ConnectionBar(state);
const fly = new FlyTab(state);
const parameters = new ParameterTable(state);
const consoleTab = new ConsoleTab(state);
const inspector = new InspectorTab(state);
const sensors = new SensorBench(state);
const plots = new PlotTab(state);
const track = new TrackTab(state);
const logs = new LogsTab(state);
const router = new TabRouter({ fly, parameters, console: consoleTab, inspector, sensors, plots, track, logs },
  (tab) => postToHost({ type: 'tab', tab }));

const root = document.getElementById('root') ?? document.body;
root.append(el('div', { className: 'dashboard' }, bar.root, router.strip, router.body));

let framePending = false;

function requestFrame(): void {
  if (framePending) return;
  framePending = true;
  requestAnimationFrame(() => {
    framePending = false;
    bar.render();
    if (router.selected === 'fly') fly.frame();
    if (router.selected === 'sensors') sensors.frame();
    if (router.selected === 'plots') plots.frame();
    if (router.selected === 'track') track.frame();
  });
}

function isTab(value: unknown): value is TabId {
  return typeof value === 'string' && (TAB_IDS as readonly string[]).includes(value);
}

state.on((message: HostMessage) => {
  switch (message.type) {
    case 'snapshot':
      fly.status.reset(state.status);
      router.select(isTab(message.tab) ? message.tab : router.selected ?? 'fly', false);
      parameters.update();
      consoleTab.update();
      inspector.updateBanner();
      logs.update();
      break;
    case 'connection':
      if (message.connection === 'connecting') fly.status.reset([]);
      parameters.update();
      consoleTab.update();
      inspector.updateBanner();
      logs.update();
      break;
    case 'logs':
    case 'log_transfer':
      logs.update();
      break;
    case 'status':
      fly.status.add(message.entries);
      break;
    case 'params':
    case 'param_value':
      parameters.update();
      break;
    case 'param_result':
      parameters.showOutcome();
      break;
    case 'console':
      consoleTab.update();
      break;
    case 'shell':
      consoleTab.write(message.text);
      break;
    case 'inspector':
      inspector.update(message.messages, message.unknown);
      break;
    case 'stream_note':
      if (message.tab === 'sensors') sensors.streamNote(message.message, message.outcome, message.reason);
      break;
    case 'focus':
      if (isTab(message.tab)) router.select(message.tab, false);
      break;
    default:
      break;
  }
  requestFrame();
});

window.addEventListener('message', (event: MessageEvent) => {
  const data = event.data as HostMessage | undefined;
  if (data && typeof data === 'object' && typeof data.type === 'string') state.apply(data);
});

setInterval(requestFrame, 1000);
router.select('fly', false);
postToHost({ type: 'ready' });
