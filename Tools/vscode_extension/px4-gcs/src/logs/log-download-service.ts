// One onboard log download at a time: pick a destination, refuse when the
// folder has less free space than the log (both numbers shown), then run the
// sidecar's `log_download` with progress (bytes, %, rate) and cancel. The
// sidecar writes `<file>.part` and renames it only when complete, so a cancel
// or failure leaves no partial file. No `vscode` import: dialogs, free space
// and the finish notice are injected.
import * as path from 'path';
import { BridgeCommandError } from '../bridge/bridge-client';
import { ConnectionController } from '../connection/connection-controller';
import { LogEntryView, LogTransferView } from '../dashboard/dashboard-messages';
import { SessionJournal } from '../session/session-journal';
import { formatBytes } from './log-transfer-format';

export interface LogDownloadHost {
  /** Absolute destination chosen by the operator, or undefined when they cancelled. */
  pickDestination(entry: LogEntryView): Promise<string | undefined>;
  /** Free bytes in the folder, or undefined when it cannot be read. */
  freeBytes(folder: string): Promise<number | undefined>;
  /** A download ended (offer Open/Reveal on success, show the error otherwise). */
  finished(transfer: LogTransferView): void;
}

export interface LogDownloadOptions {
  controller: ConnectionController;
  journal: SessionJournal;
  host: LogDownloadHost;
  onTransfer(transfer: LogTransferView | null): void;
  now?: () => number;
}

interface DownloadReply {
  path: string;
  sha256: string;
  seconds: number;
  rateBps: number;
  requests: number;
}

export class LogDownloadService {
  private current: LogTransferView | null = null;
  private commandId: number | undefined;
  /** True from the first dialog to the end, so a second request cannot slip in while the first picks a file. */
  private busy = false;

  constructor(private readonly options: LogDownloadOptions) {}

  get transfer(): LogTransferView | null {
    return this.current;
  }

  get running(): boolean {
    return this.busy;
  }

  /** Run the whole flow for one list entry; resolves with the final transfer state (null when the operator backed out). */
  async download(entry: LogEntryView): Promise<LogTransferView | null> {
    if (this.busy) return this.end({ ...this.base(entry), state: 'refused', message: 'Another log download is running.' });
    this.busy = true;
    try {
      return await this.run(entry);
    } finally {
      this.busy = false;
    }
  }

  private async run(entry: LogEntryView): Promise<LogTransferView | null> {
    const dest = await this.options.host.pickDestination(entry);
    if (!dest) return null;
    const free = await this.options.host.freeBytes(path.dirname(dest));
    if (free !== undefined && entry.size > free) {
      return this.end({ ...this.base(entry), state: 'refused', path: dest,
        message: `Not downloaded: the log needs ${entry.size} bytes (${formatBytes(entry.size)}) but the folder has `
          + `${free} bytes (${formatBytes(free)}) free.` });
    }
    const note = free === undefined ? 'Free space could not be read; downloading anyway. ' : '';
    const client = this.options.controller.client;
    if (!client) return this.end({ ...this.base(entry), state: 'failed', message: 'Not connected to a vehicle.' });
    const now = this.options.now ?? Date.now;
    const started = now();
    const op = client.start<DownloadReply>('log_download', { id: entry.id, size: entry.size, path: dest });
    this.commandId = op.id;
    this.set({ ...this.base(entry), state: 'running', path: dest, message: `${note}Downloading log ${entry.id}…` });
    const progress = this.options.controller.onEvent((event) => {
      if (event.name !== 'log_progress' || event.data.id !== op.id || this.current?.state !== 'running') return;
      const received = Number(event.data.received) || 0;
      const seconds = Math.max((now() - started) / 1000, 0.001);
      this.set({ ...this.current, received, rateBps: Math.round(received / seconds) });
    });
    try {
      const reply = await op.reply;
      return this.end({ ...this.base(entry), state: 'done', received: entry.size, rateBps: reply.rateBps, path: reply.path,
        message: `${note}Log ${entry.id} saved (${formatBytes(entry.size)} in ${reply.seconds.toFixed(1)} s, `
          + `SHA-256 ${reply.sha256.slice(0, 12)}…).` }, { sha256: reply.sha256, requests: reply.requests });
    } catch (error) {
      const cancelled = error instanceof BridgeCommandError && error.code === 'CANCELLED';
      const message = cancelled ? `Log ${entry.id} download cancelled; no file was kept.`
        : `Log ${entry.id} download failed: ${error instanceof Error ? error.message : String(error)}. No file was kept.`;
      return this.end({ ...(this.current ?? this.base(entry)), state: cancelled ? 'cancelled' : 'failed', message });
    } finally {
      progress.dispose();
      this.commandId = undefined;
    }
  }

  async cancel(): Promise<boolean> {
    const client = this.options.controller.client;
    return this.commandId !== undefined && client !== undefined ? client.cancel(this.commandId) : false;
  }

  private base(entry: LogEntryView): LogTransferView {
    return { logId: entry.id, state: 'running', received: 0, total: entry.size, rateBps: 0, message: '' };
  }

  private end(transfer: LogTransferView, extra: Record<string, unknown> = {}): LogTransferView {
    this.set(transfer);
    this.options.journal.append('log_download', { id: transfer.logId, size: transfer.total, result: transfer.state,
      path: transfer.path ?? null, message: transfer.message, ...extra });
    this.options.host.finished(transfer);
    return transfer;
  }

  private set(transfer: LogTransferView): void {
    this.current = transfer;
    this.options.onTransfer(transfer);
  }
}
