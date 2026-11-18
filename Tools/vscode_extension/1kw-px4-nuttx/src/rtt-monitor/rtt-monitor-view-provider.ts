import * as crypto from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { R8Core } from '../types';
import { RttLineEnding, RttSocketClient, RttSocketState } from './rtt-socket-client';
import { logFileName, RttScrollback } from './rtt-scrollback';

export const RTT_MONITOR_VIEW = 'px4-nuttx.rttMonitor';
const CORES: R8Core[] = ['cr8_0', 'cr8_1'];
const NAMES: Record<R8Core, string> = { cr8_0: 'R8-0', cr8_1: 'R8-1' };
/** In-band report of the dual bridge when the firmware drop counter grows. */
const DROP_MARKER = /<<rtt-bridge: output dropped: (\d+) B>>/g;

/** Monitor state shown on the badge; `paused` means a load/debug holds the probe. */
export type RttMonitorState = 'connecting' | 'connected' | 'switching' | 'paused' | 'stopped' | 'failed';
/** Where a pane's text comes from: an RTT bridge port or a host serial relay. */
export type TraceSource = 'rtt' | 'serial';
/** `single` shows one core with a core switch; `split` shows both side by side. */
export type RttLayout = 'single' | 'split';

interface CoreTrace {
  scrollback: RttScrollback;
  socket: RttSocketClient;
  endpoint?: string;
  source?: TraceSource;
  /** The pane wants its source: attached, or paused around a probe job. */
  attached: boolean;
  state: RttMonitorState;
  detail?: string;
  /** Bytes the firmware reported dropped since this pane attached. */
  dropped: number;
}

/** What the Firmware Setup controller needs from the monitor. */
export interface RttTraceSink {
  attach(core: R8Core, endpoint: string, source?: TraceSource): void;
  /** Closes the panes fed by `source` (`all` for every pane); `paused` keeps their wish to trace. */
  detach(state: 'stopped' | 'paused' | 'switching', detail?: string, source?: TraceSource | 'all'): void;
  fail(core: R8Core, detail: string): void;
  /** The first core traced over RTT, attached or paused. */
  attachedCore(): R8Core | undefined;
  /** Cores whose pane is attached (or paused) for `source`, or for any source. */
  attachedCores(source?: TraceSource): R8Core[];
  setLayout(layout: RttLayout): void;
  reveal(): Promise<void>;
}

/** CSP for the monitor page: scripts only by nonce, no inline script. */
export function monitorCsp(cspSource: string, nonce: string): string {
  // xterm's DOM renderer adds a <style> element at runtime, so styles allow inline.
  return `default-src 'none'; script-src 'nonce-${nonce}'; style-src ${cspSource} 'unsafe-inline'; font-src ${cspSource};`;
}

/**
 * Bottom-panel RTT Monitor. The extension host owns one TCP client per core
 * (RTT bridge port or serial relay); the webview only draws text and returns
 * input. Each core keeps its own scrollback so traces never mix.
 */
export class RttMonitorViewProvider implements vscode.WebviewViewProvider, RttTraceSink, vscode.Disposable {
  private view?: vscode.WebviewView;
  private readonly traces = new Map<R8Core, CoreTrace>();
  /** The pane the toolbar and view-title commands act on. */
  private shown: R8Core = 'cr8_0';
  private layout: RttLayout = 'single';
  private readonly disposables: vscode.Disposable[] = [];

  private onSwitchCore?: (core: R8Core) => Promise<void>;

  constructor(private readonly extensionUri: vscode.Uri, private readonly workspaceRoot: string,
    private readonly setupName: () => string) {
    for (const core of CORES) {
      this.traces.set(core, {
        scrollback: new RttScrollback(this.config('scrollback', 5000)), attached: false, state: 'stopped', dropped: 0,
        socket: new RttSocketClient({ onData: (text) => this.received(core, text), onState: (state, detail) => this.socketState(core, state, detail) }),
      });
    }
    this.disposables.push(vscode.workspace.onDidChangeConfiguration?.((event) => {
      if (event.affectsConfiguration('px4Nuttx.rtt')) {
        for (const trace of this.traces.values()) { trace.scrollback.setLimit(this.config('scrollback', 5000)); }
        this.replay();
      }
    }) || { dispose() {} });
  }

  public resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    const dist = vscode.Uri.joinPath(this.extensionUri, 'dist');
    view.webview.options = { enableScripts: true, localResourceRoots: [dist, vscode.Uri.joinPath(this.extensionUri, 'media')] };
    const nonce = crypto.randomBytes(16).toString('base64');
    const asset = (name: string) => view.webview.asWebviewUri(vscode.Uri.joinPath(dist, name));
    const css = view.webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'media', 'rtt-monitor.css'));
    view.webview.html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${monitorCsp(view.webview.cspSource, nonce)}">
<link rel="stylesheet" href="${asset('xterm.css')}"><link rel="stylesheet" href="${css}"><title>RTT Monitor</title></head>
<body><div id="root"></div><script nonce="${nonce}" src="${asset('rtt-monitor-webview.js')}"></script></body></html>`;
    this.disposables.push(view.webview.onDidReceiveMessage((message) => { void this.message(message); }),
      view.onDidChangeVisibility(() => { if (view.visible) { this.replay(); } }),
      view.onDidDispose(() => { if (this.view === view) { this.view = undefined; } }));
  }

  public attach(core: R8Core, endpoint: string, source: TraceSource = 'rtt'): void {
    const trace = this.traces.get(core)!;
    if (this.layout === 'single') { this.shown = core; }
    if (trace.endpoint !== endpoint || trace.source !== source || !trace.attached) { trace.dropped = 0; }
    Object.assign(trace, { endpoint, source, attached: true });
    trace.socket.connect(endpoint);
    this.replay();
  }

  public detach(state: 'stopped' | 'paused' | 'switching', detail?: string, source: TraceSource | 'all' = 'rtt'): void {
    for (const core of CORES) {
      const trace = this.traces.get(core)!;
      if (!trace.attached || (source !== 'all' && trace.source !== source)) { continue; }
      if (state !== 'paused') { trace.attached = false; }
      trace.socket.close();
      this.setState(core, state, detail);
    }
  }

  public fail(core: R8Core, detail: string): void {
    const trace = this.traces.get(core)!;
    trace.socket.close();
    trace.attached = false;
    if (this.layout === 'single') { this.shown = core; }
    this.setState(core, 'failed', detail);
  }

  public attachedCore(): R8Core | undefined { return this.attachedCores('rtt')[0]; }

  public attachedCores(source?: TraceSource): R8Core[] {
    return CORES.filter((core) => { const trace = this.traces.get(core)!; return trace.attached && (!source || trace.source === source); });
  }

  public setLayout(layout: RttLayout): void {
    if (layout === this.layout) { return; }
    this.layout = layout;
    this.replay();
  }

  public getLayout(): RttLayout { return this.layout; }

  /** Picking the other core while one is traced moves the bridge to it (single layout). */
  public setSwitchHandler(handler: (core: R8Core) => Promise<void>): void { this.onSwitchCore = handler; }

  public async reveal(): Promise<void> {
    await vscode.commands.executeCommand(`${RTT_MONITOR_VIEW}.focus`);
  }

  public clear(core: R8Core = this.shown): void {
    const trace = this.traces.get(core)!;
    trace.scrollback.clear();
    trace.dropped = 0;
    this.post({ type: 'reset', core, text: '' });
    this.postState(core);
  }

  public async copy(selection?: string, core: R8Core = this.shown): Promise<void> {
    await vscode.env.clipboard.writeText(selection || this.traces.get(core)!.scrollback.text(this.timestamps()));
    void vscode.window.setStatusBarMessage?.('RTT trace copied', 2000);
  }

  /** Writes one core's buffer under logs/rtt/ and offers to reveal it. */
  public async saveLog(core: R8Core = this.shown): Promise<string> {
    const folder = path.join(this.workspaceRoot, 'logs', 'rtt');
    await fs.promises.mkdir(folder, { recursive: true });
    const file = path.join(folder, logFileName(this.setupName(), core));
    await fs.promises.writeFile(file, this.traces.get(core)!.scrollback.text(true));
    void vscode.window.showInformationMessage(`RTT log saved: ${path.relative(this.workspaceRoot, file)}`, 'Reveal').then((choice) => {
      if (choice === 'Reveal') { void vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(file)); }
    });
    return file;
  }

  public async toggleTimestamps(): Promise<void> {
    await vscode.workspace.getConfiguration('px4Nuttx.rtt').update('timestamps', !this.timestamps(), vscode.ConfigurationTarget.Global);
    this.replay();
  }

  /** Test seam: one core's plain buffer. */
  public bufferText(core: R8Core = this.shown): string { return this.traces.get(core)!.scrollback.text(false); }

  public stateOf(core: R8Core): { state: RttMonitorState; detail?: string; endpoint?: string; source?: TraceSource; dropped: number } {
    const trace = this.traces.get(core)!;
    return { state: trace.state, detail: trace.detail, endpoint: trace.endpoint, source: trace.source, dropped: trace.dropped };
  }

  /** Sends one line to a core's pane; false when that pane is not connected. */
  public send(text: string, core: R8Core = this.shown): boolean {
    return this.traces.get(core)!.socket.send(text, this.config<RttLineEnding>('lineEnding', 'crlf'));
  }

  private async message(message: { type: string; text?: string; core?: R8Core }): Promise<void> {
    const core = message.core && CORES.includes(message.core) ? message.core : undefined;
    if (message.type === 'ready') { this.replay(); }
    else if (message.type === 'focus' && core) { this.shown = core; }
    else if (message.type === 'input' && typeof message.text === 'string') {
      if (!this.send(message.text, core)) {
        void vscode.window.showWarningMessage(`${NAMES[core || this.shown]} is not connected; start RTT from Firmware Setup.`);
      }
    } else if (message.type === 'switchCore' && core && core !== this.shown && this.layout === 'single') {
      this.shown = core;
      this.replay();
      const traced = this.attachedCore();
      if (traced && traced !== core && this.onSwitchCore) { await this.onSwitchCore(core); }
    } else if (message.type === 'copy') { await this.copy(message.text, core); }
    else if (message.type === 'save') { await this.saveLog(core); }
    else if (message.type === 'clear') { this.clear(core); }
    else if (message.type === 'toggleTimestamps') { await this.toggleTimestamps(); }
  }

  private received(core: R8Core, text: string): void {
    const trace = this.traces.get(core)!;
    if (!trace.attached) { return; }
    let dropped = 0;
    for (const match of text.matchAll(DROP_MARKER)) { dropped += Number(match[1]); }
    const rendered = trace.scrollback.append(text, this.timestamps());
    this.post({ type: 'data', core, text: rendered });
    if (dropped) { trace.dropped += dropped; this.postState(core); }
  }

  private socketState(core: R8Core, state: RttSocketState, detail?: string): void {
    if (!this.traces.get(core)!.attached) { return; }
    if (state === 'closed' && !detail) { return; }
    this.setState(core, state === 'closed' ? 'stopped' : state, detail);
  }

  private setState(core: R8Core, state: RttMonitorState, detail?: string): void {
    const trace = this.traces.get(core)!;
    trace.state = state;
    trace.detail = detail;
    this.postState(core);
  }

  private postState(core: R8Core): void {
    const trace = this.traces.get(core)!;
    const label = trace.state[0].toUpperCase() + trace.state.slice(1);
    const where = [NAMES[core], trace.source === 'serial' ? 'serial' : undefined, trace.endpoint].filter(Boolean).join(' · ');
    const dropped = trace.dropped ? ` · output dropped: ${trace.dropped} B` : '';
    this.post({ type: 'state', core, state: trace.state, text: `${label}${trace.detail ? `: ${trace.detail}` : ''} · ${where}${dropped}`,
      dropped: trace.dropped, timestamps: this.timestamps() });
  }

  private replay(): void {
    this.post({ type: 'layout', layout: this.layout, shown: this.shown });
    for (const core of CORES) {
      this.post({ type: 'reset', core, text: this.traces.get(core)!.scrollback.render(this.timestamps()) });
      this.postState(core);
    }
  }

  private post(message: Record<string, unknown>): void { void this.view?.webview.postMessage(message); }

  private timestamps(): boolean { return this.config('timestamps', true); }

  private config<T>(key: string, fallback: T): T {
    return vscode.workspace.getConfiguration('px4Nuttx.rtt').get<T>(key, fallback) ?? fallback;
  }

  public dispose(): void {
    for (const trace of this.traces.values()) { trace.socket.close(); }
    for (const disposable of this.disposables) { disposable.dispose(); }
  }
}
