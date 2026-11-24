// The NSH console over MAVLink SERIAL_CONTROL. The console is the stated
// exception to the guarded buttons, so it opens behind one warning per
// connection and every line sent is journaled. No `vscode` import: the modal
// is injected, and the tests drive this class with the real sidecar.
import { ConnectionController } from '../connection/connection-controller';
import { ConsoleState } from '../dashboard/dashboard-messages';
import { SessionJournal } from '../session/session-journal';
import { ConsoleLineAssembler } from './console-line-assembler';

export const CONSOLE_WARNING = 'The NSH console is a direct shell on the vehicle. Commands typed here run at once '
  + 'and skip the confirmations of the Arm, Mode and Reboot buttons; `commander arm -f` forces arming.';
export const CONSOLE_ACCEPT = 'Open Console';
/** The sidecar refuses longer `shell_write` input. */
const WRITE_CHUNK = 4096;

export interface ConsoleSessionOptions {
  controller: ConnectionController;
  journal: SessionJournal;
  /** Show the warning modal; true when the operator chose Open Console. */
  confirm(message: string): Promise<boolean>;
  /** `px4Gcs.control.enabled`: false keeps the console closed. */
  controlEnabled(): boolean;
  onState(state: ConsoleState): void;
  onOutput(text: string): void;
  log(line: string): void;
}

export class ConsoleSession {
  private accepted = false;
  private opened = false;
  private stateValue: ConsoleState = { state: 'closed' };
  private readonly assembler = new ConsoleLineAssembler();
  private readonly subscriptions: { dispose(): void }[];

  constructor(private readonly options: ConsoleSessionOptions) {
    this.subscriptions = [
      options.controller.onDidChangeState((state) => {
        // A new connection asks again; a lost link that recovers keeps its answer.
        if (state === 'connecting' || state === 'idle') {
          this.accepted = false;
          this.opened = false;
          this.assembler.reset();
          this.setState({ state: 'closed' });
        }
      }),
      options.controller.onEvent((event) => {
        if (event.name !== 'shell_data' || !this.opened) return;
        const text = (event.data as { text?: unknown }).text;
        if (typeof text === 'string') options.onOutput(text);
      }),
    ];
  }

  get state(): ConsoleState {
    return this.stateValue;
  }

  get isOpen(): boolean {
    return this.opened;
  }

  /** Open the shell, asking first when this connection has not been warned yet. */
  async open(): Promise<ConsoleState> {
    if (this.opened) return this.stateValue;
    const blocked = this.blockedReason();
    if (blocked) return this.setState({ state: 'disabled', reason: blocked });
    if (!this.accepted) {
      const ok = await this.options.confirm(CONSOLE_WARNING);
      if (!ok) {
        this.options.journal.append('console_declined', {});
        return this.setState({ state: 'declined' });
      }
      this.accepted = true;
    }
    const client = this.options.controller.client;
    if (!client) return this.setState({ state: 'disabled', reason: 'Connect to a vehicle to use the console.' });
    try {
      await client.request('shell_open');
    } catch (error) {
      this.options.log(`console: ${errorText(error)}`);
      return this.setState({ state: 'disabled', reason: `The shell did not open: ${errorText(error)}` });
    }
    this.opened = true;
    this.assembler.reset();
    this.options.journal.append('console_opened', { systemId: this.options.controller.link?.systemId ?? null });
    return this.setState({ state: 'open' });
  }

  /** Send typed text; journals each line whose line end is part of `data`. */
  async write(data: string): Promise<boolean> {
    const client = this.options.controller.client;
    if (!this.opened || !client || !this.options.controlEnabled()) return false;
    for (const line of this.assembler.feed(data)) this.options.journal.append('console_line', { line });
    try {
      for (let at = 0; at < data.length; at += WRITE_CHUNK) {
        await client.request('shell_write', { data: data.slice(at, at + WRITE_CHUNK) });
      }
      return true;
    } catch (error) {
      this.options.log(`console write: ${errorText(error)}`);
      return false;
    }
  }

  /** Close the shell (console tab or dashboard closed). */
  async close(): Promise<void> {
    if (!this.opened) return;
    this.opened = false;
    this.assembler.reset();
    this.setState({ state: 'closed' });
    try {
      await this.options.controller.client?.request('shell_close');
    } catch (error) {
      this.options.log(`console close: ${errorText(error)}`);
    }
  }

  dispose(): void {
    for (const subscription of this.subscriptions) subscription.dispose();
  }

  private blockedReason(): string | undefined {
    if (!this.options.controlEnabled()) {
      return 'Vehicle control is off (setting px4Gcs.control.enabled), so the console is closed.';
    }
    if (!this.options.controller.client) return 'Connect to a vehicle to use the console.';
    return undefined;
  }

  private setState(state: ConsoleState): ConsoleState {
    this.stateValue = state;
    this.options.onState(state);
    return state;
  }
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
