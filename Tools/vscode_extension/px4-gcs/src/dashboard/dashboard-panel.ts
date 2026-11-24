// The single dashboard WebviewPanel. Reopening or revealing replays the state
// held by the router (store values, status log, parameters, console state).
import * as vscode from 'vscode';
import { createNonce, dashboardHtml } from './dashboard-csp';
import { TabId, WebviewMessage } from './dashboard-messages';
import { DashboardRouter } from './dashboard-router';

const VIEW_TYPE = 'px4Gcs.dashboard';

export class DashboardPanel {
  private panel: vscode.WebviewPanel | undefined;

  constructor(private readonly extensionUri: vscode.Uri, private readonly router: DashboardRouter) {}

  /** Show the dashboard (create it once), optionally on a given tab. */
  open(tab?: TabId): void {
    if (this.panel) {
      this.panel.reveal(undefined, false);
    } else {
      this.panel = this.create();
    }
    if (tab) {
      void this.panel.webview.postMessage({ type: 'focus', tab });
      void this.router.selectTab(tab);
    }
  }

  dispose(): void {
    this.panel?.dispose();
  }

  private create(): vscode.WebviewPanel {
    const dist = vscode.Uri.joinPath(this.extensionUri, 'dist');
    const media = vscode.Uri.joinPath(this.extensionUri, 'media');
    const panel = vscode.window.createWebviewPanel(VIEW_TYPE, 'Px4-GCS', vscode.ViewColumn.Active, {
      enableScripts: true,
      retainContextWhenHidden: false,
      localResourceRoots: [dist, media],
    });
    panel.iconPath = vscode.Uri.joinPath(media, 'icon.png');
    const webview = panel.webview;
    const asset = (base: vscode.Uri, name: string): string => webview.asWebviewUri(vscode.Uri.joinPath(base, name)).toString();
    webview.html = dashboardHtml({
      cspSource: webview.cspSource,
      nonce: createNonce(),
      scriptUri: asset(dist, 'dashboard.js'),
      styleUris: [asset(dist, 'xterm.css'), asset(dist, 'uplot.css'), asset(media, 'dashboard.css')],
    });
    this.router.attach((message) => { void webview.postMessage(message); });
    const subscriptions = [
      webview.onDidReceiveMessage((message: WebviewMessage) => {
        void this.router.handle(message);
      }),
      panel.onDidChangeViewState(({ webviewPanel }) => {
        void this.router.setVisible(webviewPanel.visible);
      }),
      panel.onDidDispose(() => {
        for (const subscription of subscriptions) subscription.dispose();
        this.panel = undefined;
        void this.router.detach();
      }),
    ];
    void this.router.setVisible(true);
    return panel;
  }
}
