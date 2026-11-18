// Run Doctor, Quick Connect, Connect and Disconnect: trust gate, single-owner
// rule, delayed progress with cancel, and actionable errors.
import * as vscode from 'vscode';
import { exitError } from '../bridge/bridge-client';
import { runDoctorProcess } from '../bridge/bridge-process';
import { ConnectArgs, DoctorData } from '../bridge/bridge-protocol';
import { GcsOutput } from '../gcs-output';
import { readGcsSettings } from '../gcs-settings';
import { workspaceIsTrusted } from '../workspace-trust';
import { ConnectionController } from './connection-controller';
import { describeError, PIP_REQUIREMENTS, showDescribedError } from './connection-errors';
import {
  confirmUdpBind, pickTransport, REMEMBERED_LINK_KEY, RememberedLink, serialArgs, udpArgs,
} from './quick-connect';

const PROGRESS_DELAY_MS = 300;

/** False (after telling the user) while the workspace is untrusted: nothing may be spawned then. */
async function requireTrust(): Promise<boolean> {
  if (workspaceIsTrusted()) return true;
  const choice = await vscode.window.showWarningMessage('1KW-Px4-GCS: Connecting needs a trusted workspace.',
    'Manage Workspace Trust');
  if (choice) await vscode.commands.executeCommand('workbench.trust.manage');
  return false;
}

/** Show a cancellable progress notification only when `work` is still running after 300 ms. */
function delayedProgress(title: string, work: Promise<unknown>, onCancel: () => void): void {
  let done = false;
  const finish = (): void => { done = true; clearTimeout(timer); };
  work.then(finish, finish);
  const timer = setTimeout(() => {
    if (done) return;
    void vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title, cancellable: true },
      (_progress, token) => {
        token.onCancellationRequested(onCancel);
        return work.then(() => undefined, () => undefined);
      });
  }, PROGRESS_DELAY_MS);
}

export class ConnectionCommands {
  constructor(private readonly context: vscode.ExtensionContext, private readonly controller: ConnectionController,
    private readonly output: GcsOutput, private readonly pythonDir: string) {}

  register(): vscode.Disposable[] {
    return [
      vscode.commands.registerCommand('px4Gcs.runDoctor', () => this.runDoctor()),
      vscode.commands.registerCommand('px4Gcs.quickConnect', () => this.connect(false)),
      vscode.commands.registerCommand('px4Gcs.connect', () => this.connect(true)),
      vscode.commands.registerCommand('px4Gcs.disconnect', () => this.controller.disconnect()),
    ];
  }

  async runDoctor(): Promise<DoctorData | undefined> {
    if (!(await requireTrust())) return undefined;
    const { pythonPath } = readGcsSettings();
    const { exit, line } = await runDoctorProcess(pythonPath, this.pythonDir);
    if (exit.spawnError || !line) {
      const error = exitError(exit);
      this.output.log(`doctor: ${error.message}`);
      await showDescribedError(describeError(error, pythonPath));
      return undefined;
    }
    let report: DoctorData;
    try {
      report = JSON.parse(line) as DoctorData;
    } catch {
      this.output.log(`doctor: unreadable output ${line.slice(0, 200)}`);
      return undefined;
    }
    this.output.log(`doctor: ${line}`);
    const summary = `Python ${report.python}, pymavlink ${report.pymavlink ?? 'missing'}, pyserial ${report.pyserial ?? 'missing'}`;
    if (!report.pythonOk || report.missing.length > 0) {
      const fix = report.missing.length > 0 ? ` Install with: "${pythonPath}" -m pip install ${PIP_REQUIREMENTS}` : '';
      const choice = await vscode.window.showErrorMessage(`1KW-Px4-GCS doctor: ${summary}.${fix}`, 'Open Settings');
      if (choice) await vscode.commands.executeCommand('workbench.action.openSettings', 'px4Gcs.pythonPath');
    } else {
      void vscode.window.showInformationMessage(`1KW-Px4-GCS doctor: ${summary}. Ready.`);
    }
    return report;
  }

  /** `pick` is the Connect command (choose transport and port); Quick Connect decides alone where it can. */
  async connect(pick: boolean): Promise<void> {
    if (!(await requireTrust())) return;
    if (this.controller.state !== 'idle') {
      const choice = await vscode.window.showWarningMessage(
        '1KW-Px4-GCS: a vehicle connection is already open. Disconnect it first?', { modal: true }, 'Disconnect');
      if (choice === 'Disconnect') await this.controller.disconnect();
      return;
    }
    const settings = readGcsSettings();
    const transport = pick ? await pickTransport(settings) : settings.transport;
    if (!transport) return;
    if (transport === 'udp' && !(await confirmUdpBind(settings.udpHost, settings.udpPort))) return;
    const remembered = this.context.workspaceState.get<RememberedLink>(REMEMBERED_LINK_KEY);
    let chosen: ConnectArgs | undefined;
    this.output.resetOnce();
    const work = this.controller.connect(settings.pythonPath, async (client) => {
      chosen = transport === 'udp' ? udpArgs(settings) : await serialArgs(client, settings, remembered, pick);
      if (chosen) this.output.log(`connecting: ${JSON.stringify({ ...chosen, sessionId: undefined })}`);
      return chosen;
    });
    delayedProgress('1KW-Px4-GCS: connecting', work, () => this.controller.cancel());
    try {
      const link = await work;
      if (!link) {
        this.output.log('connect cancelled');
        return;
      }
      this.output.log(`connected: system ${link.systemId} over ${link.transport}${link.baud ? ` @ ${link.baud}` : ''}`);
      if (chosen?.transport === 'serial' && typeof link.baud === 'number') {
        await this.context.workspaceState.update(REMEMBERED_LINK_KEY, { device: chosen.device, baud: link.baud });
      }
    } catch (error) {
      this.output.log(`connect failed: ${error instanceof Error ? error.message : String(error)}`);
      await showDescribedError(describeError(error, settings.pythonPath));
    }
  }
}
