// Wording of the guarded-command modals: each names the action, the vehicle,
// the transport, the armed state and mode, and the consequence. Pure strings.
import { ModeEntry } from '../bridge/bridge-protocol';
import { AUTOMATIC_MODES, GuardedAction, VehicleSnapshot } from './command-preconditions';

export interface Confirmation {
  message: string;
  detail: string;
  /** The confirm button repeats the verb; Cancel is the default. */
  button: string;
}

export const NO_RC_SENTENCE = 'No RC transmitter or kill switch is part of this setup; '
  + 'Hold, Land and Return are the ways to stop the vehicle.';

function vehicleLine(state: VehicleSnapshot): string {
  const id = `system ${state.systemId ?? '?'}, component ${state.componentId ?? '?'}`;
  const armed = state.armed === null ? 'armed state unknown' : state.armed ? 'ARMED' : 'disarmed';
  return `Vehicle ${id} on ${state.transport}; ${armed}; mode ${state.modeName ?? 'unknown'}.`;
}

export function commandConfirmation(action: GuardedAction, state: VehicleSnapshot, mode?: ModeEntry): Confirmation {
  const lines = [vehicleLine(state)];
  const current = state.modeName ?? 'unknown';
  switch (action) {
    case 'arm':
      lines.push(`Propellers may spin. The vehicle arms in ${current}.`);
      if (state.modeKey && AUTOMATIC_MODES.has(state.modeKey)) {
        lines.push(`${current} is an automatic mode: the vehicle acts on it as soon as it is armed.`, NO_RC_SENTENCE);
      }
      return { message: 'Arm the vehicle?', detail: lines.join('\n'), button: 'Arm' };
    case 'disarm':
      lines.push('Motors stop. PX4 refuses to disarm while flying.');
      return { message: 'Disarm the vehicle?', detail: lines.join('\n'), button: 'Disarm' };
    case 'set_mode': {
      const target = mode?.name ?? 'unknown';
      lines.push(`Mode change: ${current} → ${target}.`);
      if (mode?.needsSticks) {
        lines.push(`${target} needs stick input. This extension sends no stick input, so the vehicle will refuse `
          + `${target} or enter its manual-control-loss failsafe.`);
      }
      if (state.armed) lines.push('The vehicle is armed: it changes its behaviour immediately.');
      return { message: `Change the flight mode to ${target}?`, detail: lines.join('\n'), button: 'Change mode' };
    }
    case 'reboot':
      lines.push('The autopilot restarts. A RAM-loaded image is lost and must be loaded again.');
      return { message: 'Reboot the vehicle?', detail: lines.join('\n'), button: 'Reboot vehicle' };
  }
}

/** "MAV_RESULT_TEMPORARILY_REJECTED" -> "temporarily rejected". */
export function resultText(result: string): string {
  return result.replace(/^MAV_RESULT_/, '').toLowerCase().replace(/_/g, ' ');
}
