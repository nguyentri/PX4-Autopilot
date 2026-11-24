// `.tlog` recording, only on an explicit command. The sidecar writes the file
// (raw frames of the pinned vehicle, both directions) and closes it on stop,
// on disconnect and on its own shutdown; this class names the file, keeps the
// state for the status bar, tree and dashboard, and journals start and stop.
// No `vscode` import.
import * as fs from 'fs';
import * as path from 'path';
import { ConnectionController } from '../connection/connection-controller';
import { RecordingView } from '../dashboard/dashboard-messages';
import { SessionJournal } from './session-journal';

export interface SessionRecorderOptions {
  controller: ConnectionController;
  journal: SessionJournal;
  /** The folder for new recordings (the setting, else the extension's global storage). */
  directory(): string;
  onState(recording: RecordingView): void;
  now?: () => Date;
}

/** `px4-gcs-20261118T101502Z.tlog` */
export function recordingFileName(now: Date): string {
  return `px4-gcs-${now.toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z')}.tlog`;
}

export class SessionRecorder {
  private current: RecordingView = { active: false };
  private readonly subscriptions: { dispose(): void }[];

  constructor(private readonly options: SessionRecorderOptions) {
    this.subscriptions = [
      options.controller.onEvent((event) => {
        if (event.name !== 'recording') return;
        const data = event.data as { state?: string; path?: string; reason?: string; frames?: number; bytes?: number };
        if (data.state === 'stopped') this.stopped(data.path, data.reason ?? 'operator', data.frames, data.bytes);
      }),
      // The sidecar closes the file when it exits; without a `stopped` event the state still has to end.
      options.controller.onDidChangeState((state) => {
        if (state === 'idle' && this.current.active) this.stopped(this.current.path, 'disconnect');
      }),
    ];
  }

  get state(): RecordingView {
    return this.current;
  }

  /** Start a recording; returns the file path, or throws with an operator-readable message. */
  async start(): Promise<string> {
    const { controller } = this.options;
    const client = controller.client;
    if (!client || controller.state !== 'connected') throw new Error('Connect to a vehicle before recording.');
    if (this.current.active) throw new Error(`Already recording to ${this.current.path}.`);
    const folder = this.options.directory();
    await fs.promises.mkdir(folder, { recursive: true });
    const file = path.join(folder, recordingFileName((this.options.now ?? (() => new Date()))()));
    await client.request('record_start', { path: file });
    this.set({ active: true, path: file });
    this.options.journal.append('recording', { state: 'started', path: file });
    return file;
  }

  /** Stop the running recording; resolves with its path (undefined when none was running). */
  async stop(): Promise<string | undefined> {
    if (!this.current.active) return undefined;
    const file = this.current.path;
    const client = this.options.controller.client;
    if (client) {
      const reply = await client.request<{ stopped: boolean; frames?: number; bytes?: number }>('record_stop');
      if (this.current.active) this.stopped(file, 'operator', reply.frames, reply.bytes);
    } else {
      this.stopped(file, 'disconnect');
    }
    return file;
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose();
  }

  private stopped(file: string | undefined, reason: string, frames?: number, bytes?: number): void {
    if (!this.current.active) return;
    this.set({ active: false, path: file, reason, frames });
    this.options.journal.append('recording', { state: 'stopped', path: file ?? null, reason, frames: frames ?? null,
      bytes: bytes ?? null });
  }

  private set(recording: RecordingView): void {
    this.current = recording;
    this.options.onState(recording);
  }
}
