// Pure guard rules for the vehicle-changing buttons. Checked before the modal
// and again after it closes, because the vehicle may change while it is open.
// No `vscode` import: the tests call these functions directly.
import { ModeEntry } from '../bridge/bridge-protocol';

export type GuardedAction = 'arm' | 'disarm' | 'set_mode' | 'reboot';

/** A heartbeat older than this refuses every guarded action. */
export const HEARTBEAT_MAX_AGE_MS = 2000;

/** The state a guard decision reads, captured at one instant. */
export interface VehicleSnapshot {
  controlEnabled: boolean;
  connection: string;
  /** Milliseconds since the last heartbeat, null when none arrived on this connection. */
  heartbeatAgeMs: number | null;
  armed: boolean | null;
  modeKey: string | null;
  modeName: string | null;
  systemId: number | null;
  componentId: number | null;
  /** "/dev/ttyUSB0 @ 57600" or "UDP 127.0.0.1:14550". */
  transport: string;
  /** Mode keys the vehicle reported as available; null when it reported none. */
  availableModes: string[] | null;
}

/** Why the shared guard refuses without a dialog; undefined when the action may be offered. */
export function linkRefusal(state: VehicleSnapshot): string | undefined {
  if (!state.controlEnabled) return 'Vehicle control is off (setting px4Gcs.control.enabled).';
  if (state.connection !== 'connected') return 'No vehicle is connected (the link is not up).';
  if (state.heartbeatAgeMs === null || state.heartbeatAgeMs > HEARTBEAT_MAX_AGE_MS) {
    return 'The last heartbeat is older than 2 s, so the vehicle state is not current.';
  }
  return undefined;
}

/** Refusal for a guarded action, or undefined when it may go ahead. */
export function commandRefusal(action: GuardedAction, state: VehicleSnapshot, mode?: ModeEntry): string | undefined {
  const link = linkRefusal(state);
  if (link) return link;
  if (action === 'reboot' && state.armed !== false) return 'Reboot is refused while the vehicle is armed.';
  if (action === 'set_mode') {
    if (!mode) return 'Unknown flight mode.';
    const unavailable = modeUnavailableReason(mode.key, state.availableModes);
    if (unavailable) return `${mode.name} is ${unavailable}.`;
  }
  return undefined;
}

/** "not available on this vehicle" when the vehicle reported its modes and this one is missing. */
export function modeUnavailableReason(key: string, available: string[] | null): string | undefined {
  return available && !available.includes(key) ? 'not available on this vehicle' : undefined;
}

/** Modes the vehicle acts on by itself as soon as it is armed. */
export const AUTOMATIC_MODES: ReadonlySet<string> = new Set([
  'AUTO_TAKEOFF', 'AUTO_MISSION', 'AUTO_RTL', 'AUTO_LAND', 'AUTO_LOITER',
]);
