// Onboard logs: Refresh asks the vehicle for its list. Three results are kept
// apart: the table (id, date, size, Download); "the vehicle reported no logs"
// when PX4 stayed silent while heartbeats continued; and the link error when
// the link was lost. One download at a time, with bytes, percent, rate and
// Cancel. Everything is text nodes (dom-helpers).
import { LogEntryView, LogTransferView, NO_LOGS_TEXT } from '../../dashboard/dashboard-messages';
import { formatBytes, logDate, transferText } from '../../logs/log-transfer-format';
import { button, clear, el, setText } from '../dom-helpers';
import { TabStateBanner } from '../tab-state-banner';
import { TabView } from '../tab-router';
import { postToHost, WebviewState } from '../webview-state';

const TRANSFER_TITLE: Record<LogTransferView['state'], string> = {
  running: 'Downloading', done: 'Saved', cancelled: 'Cancelled', failed: 'Failed', refused: 'Not downloaded',
};

export class LogsTab implements TabView {
  readonly root = el('div', { className: 'logs-tab' });
  private readonly banner = new TabStateBanner('');
  private readonly refresh = button('Refresh', () => postToHost({ type: 'logs_refresh' }));
  private readonly listStatus = el('p', { className: 'logs-status', attrs: { role: 'status' } });
  private readonly table = el('table', { className: 'logs-table' });
  private readonly transferBox = el('div', { className: 'logs-transfer', attrs: { role: 'status', 'aria-live': 'polite' } });
  private readonly transferTitle = el('strong');
  private readonly transferText = el('span');
  private readonly bar = el('progress', { attrs: { max: '100', value: '0' } });
  private readonly cancel = button('Cancel', () => postToHost({ type: 'log_cancel' }));
  private readonly report = button('Session Report', () => postToHost({ type: 'run', command: 'openSessionReport' }),
    { title: 'Write this session\'s HTML report next to the recordings and open it' });
  private readonly content = el('div', {}, el('div', { className: 'logs-toolbar' }, this.refresh, ' ', this.report),
    this.transferBox,
    this.listStatus, this.table);
  private renderedEntries: LogEntryView[] | undefined;

  constructor(private readonly state: WebviewState) {
    this.transferBox.append(this.transferTitle, ' ', this.transferText, this.bar, this.cancel);
    this.root.append(this.banner.root, this.content);
  }

  show(visible: boolean): void {
    if (visible) this.update();
  }

  update(): void {
    const { state } = this;
    this.banner.update(state.connected ? 'live' : 'disconnected', this.content);
    const logs = state.logs;
    const running = state.transfer?.state === 'running';
    // A list request ends PX4's running log transfer, so Refresh waits for the download.
    this.refresh.disabled = running || logs.state === 'loading' || state.connection !== 'connected';
    setText(this.listStatus, logs.state === 'idle' ? 'Press Refresh to ask the vehicle for its log list.'
      : logs.state === 'loading' ? 'Asking the vehicle for its log list…'
        : logs.state === 'error' ? logs.message
          : !logs.entries.length ? NO_LOGS_TEXT
            : `${logs.entries.length} log${logs.entries.length === 1 ? '' : 's'}${logs.truncated ? ' (list truncated at 2,000)' : ''}.`);
    this.listStatus.classList.toggle('error', logs.state === 'error');
    const entries = logs.state === 'done' ? logs.entries : [];
    if (entries !== this.renderedEntries) this.renderTable(entries);
    for (const node of this.table.querySelectorAll('button')) node.disabled = running || state.connection !== 'connected';
    this.renderTransfer(state.transfer);
  }

  private renderTable(entries: LogEntryView[]): void {
    this.renderedEntries = entries;
    clear(this.table);
    this.table.hidden = !entries.length;
    if (!entries.length) return;
    const head = el('tr', {}, el('th', { text: 'Id' }), el('th', { text: 'Date' }), el('th', { text: 'Size' }), el('th'));
    const body = el('tbody');
    for (const entry of entries) {
      body.appendChild(el('tr', {},
        el('td', { text: String(entry.id) }),
        el('td', { text: logDate(entry.timeUtc) }),
        el('td', { className: 'num', text: formatBytes(entry.size) }),
        el('td', {}, button('Download', () => postToHost({ type: 'log_download', id: entry.id }),
          { attrs: { 'aria-label': `Download log ${entry.id}` } }))));
    }
    this.table.append(el('thead', {}, head), body);
  }

  private renderTransfer(t: LogTransferView | null): void {
    this.transferBox.hidden = !t;
    if (!t) return;
    setText(this.transferTitle, `${TRANSFER_TITLE[t.state]} log ${t.logId}:`);
    setText(this.transferText, t.state === 'running' ? transferText(t) : t.message);
    this.bar.hidden = t.state !== 'running';
    this.bar.value = t.total ? Math.floor((100 * t.received) / t.total) : 0;
    this.cancel.hidden = t.state !== 'running';
    this.transferBox.dataset.state = t.state;
  }
}
