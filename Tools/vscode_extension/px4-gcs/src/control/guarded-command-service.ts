// Every vehicle-changing button and palette command runs through here:
// refuse without a dialog when a precondition fails, confirm with a modal,
// check again, send once, name the acknowledgement, journal the outcome.
// Never retries and never sends a forced arm. No `vscode` import: the modal is
// injected so the tests drive the service against the real sidecar.
import { BridgeCommandError } from '../bridge/bridge-client';
import { HeartbeatData, ModeEntry } from '../bridge/bridge-protocol';
import { ConnectionController } from '../connection/connection-controller';
import { SessionJournal } from '../session/session-journal';
import { VehicleStateStore } from '../vehicle/vehicle-state-store';
import { commandRefusal, GuardedAction, VehicleSnapshot } from './command-preconditions';
import { commandConfirmation, Confirmation, resultText } from './confirmation-text';

/** The sidecar waits 3 s for the acknowledgement; this only bounds a stuck sidecar. */
const REPLY_TIMEOUT_MS = 8000;

export interface CommandOutcome {
  action: GuardedAction;
  mode?: string;
  /** refused | declined | accepted | denied | temporarily rejected | failed | timeout | ... */
  result: string;
  message: string;
}

export interface VehicleContext {
  controller: ConnectionController;
  store: VehicleStateStore;
  controlEnabled(): boolean;
  /** Wall-clock milliseconds; the tests may shift it. */
  now?(): number;
}

/** The guard inputs at this instant. */
export function captureSnapshot(context: VehicleContext): VehicleSnapshot {
  const { controller, store } = context;
  const now = context.now?.() ?? Date.now();
  const beat = store.latestSample('heartbeat');
  const heartbeat = beat?.data as HeartbeatData | undefined;
  const link = controller.link;
  const modes = store.get<{ reported?: boolean; available?: string[] }>('modes');
  const transport = link?.transport === 'udp'
    ? `UDP ${link.host ?? '?'}:${link.udpPort ?? '?'}`
    : `${link?.port ?? 'unknown port'} @ ${link?.baud ?? '?'}`;
  return {
    controlEnabled: context.controlEnabled(),
    connection: controller.state,
    heartbeatAgeMs: beat ? Math.max(0, now - beat.ts * 1000) : null,
    armed: heartbeat ? heartbeat.armed : null,
    modeKey: heartbeat?.modeKey ?? null,
    modeName: heartbeat?.mode ?? null,
    systemId: link?.systemId ?? null,
    componentId: link?.componentId ?? null,
    transport,
    availableModes: modes?.reported && Array.isArray(modes.available) ? modes.available : null,
  };
}

export interface GuardedCommandOptions extends VehicleContext {
  journal: SessionJournal;
  /** Modal with Cancel as default; true only when the confirm button was chosen. */
  confirm(confirmation: Confirmation): Promise<boolean>;
}

export class GuardedCommandService {
  constructor(private readonly options: GuardedCommandOptions) {}

  /** The sidecar's mode table (plan decision D13: the only one). */
  modes(): ModeEntry[] {
    return this.options.controller.hello?.modes ?? [];
  }

  snapshot(): VehicleSnapshot {
    return captureSnapshot(this.options);
  }

  async run(action: GuardedAction, modeKey?: string): Promise<CommandOutcome> {
    const mode = action === 'set_mode' ? this.modes().find((m) => m.key === modeKey) : undefined;
    const base = { action, ...(modeKey ? { mode: modeKey } : {}) };
    const refused = commandRefusal(action, this.snapshot(), mode);
    if (refused) return this.finish(base, 'refused', refused, { decision: 'refused' });
    const confirmed = await this.options.confirm(commandConfirmation(action, this.snapshot(), mode));
    if (!confirmed) return this.finish(base, 'declined', 'Cancelled; nothing was sent.', { decision: 'declined' });
    const late = commandRefusal(action, this.snapshot(), mode);
    if (late) return this.finish(base, 'refused', `Not sent: ${late}`, { decision: 'confirmed' });
    const client = this.options.controller.client;
    if (!client) return this.finish(base, 'refused', 'Not sent: the link closed.', { decision: 'confirmed' });
    try {
      await client.request(action, mode ? { mode: mode.key } : undefined, { timeoutMs: REPLY_TIMEOUT_MS });
      return this.finish(base, 'accepted', `${label(action, mode)}: accepted.`, { decision: 'confirmed' });
    } catch (error) {
      const [result, message] = failure(error);
      return this.finish(base, result, `${label(action, mode)}: ${message}`, { decision: 'confirmed' });
    }
  }

  private finish(base: { action: GuardedAction; mode?: string }, result: string, message: string,
    extra: Record<string, unknown>): CommandOutcome {
    this.options.journal.append('command', { ...base, ...extra, result, message });
    return { ...base, result, message };
  }
}

function label(action: GuardedAction, mode?: ModeEntry): string {
  switch (action) {
    case 'arm': return 'Arm';
    case 'disarm': return 'Disarm';
    case 'reboot': return 'Reboot';
    case 'set_mode': return `Mode ${mode?.name ?? '?'}`;
  }
}

/** [result, message] for a failed request: the acknowledgement by name, or why there was none. */
function failure(error: unknown): [string, string] {
  if (error instanceof BridgeCommandError) {
    if (error.code === 'DENIED' && typeof error.details.result === 'string') {
      const text = resultText(error.details.result);
      return [text, text];
    }
    if (error.code === 'TIMEOUT') return ['timeout', 'timeout: no acknowledgement within 3 s'];
    return ['failed', `failed: ${error.message}`];
  }
  return ['failed', `failed: ${error instanceof Error ? error.message : String(error)}`];
}
