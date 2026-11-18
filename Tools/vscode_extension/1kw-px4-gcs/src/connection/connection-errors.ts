// Sidecar and host error codes turned into an actionable message with buttons.
import * as vscode from 'vscode';
import { BridgeCommandError } from '../bridge/bridge-client';

export const PIP_REQUIREMENTS = 'pymavlink==2.4.48 pyserial==3.5';

export interface ErrorAction {
  title: string;
  command: string;
  args?: unknown[];
}

export interface DescribedError {
  message: string;
  actions: ErrorAction[];
}

export const RUN_DOCTOR: ErrorAction = { title: 'Run Doctor', command: 'px4Gcs.runDoctor' };
export const OPEN_PYTHON_SETTING: ErrorAction = {
  title: 'Open Settings', command: 'workbench.action.openSettings', args: ['px4Gcs.pythonPath'],
};
const OPEN_SERIAL_SETTING: ErrorAction = {
  title: 'Open Settings', command: 'workbench.action.openSettings', args: ['px4Gcs.serial'],
};
const OPEN_UDP_SETTING: ErrorAction = {
  title: 'Open Settings', command: 'workbench.action.openSettings', args: ['px4Gcs.udp'],
};

interface LeaseOwner {
  kind?: string;
  sessionId?: string | null;
  pid?: number | null;
  device?: string | null;
  tcpPort?: number | null;
}

function ownerText(owner: LeaseOwner): string {
  const who = [owner.sessionId ? `session ${owner.sessionId}` : '', owner.pid ? `process ${owner.pid}` : '']
    .filter(Boolean).join(', ');
  if (owner.kind === 'firmware-workspace') {
    return `the 1KW-Px4-Nuttx serial console (${who || 'unknown session'}). `
      + 'Close the serial pane of the RTT Monitor in 1KW-Px4-Nuttx.';
  }
  return `another 1KW-Px4-GCS window (${who || 'unknown session'}). Disconnect it first.`;
}

/** `pythonPath` is quoted into the pip line exactly as the setting holds it. */
export function describeError(error: unknown, pythonPath: string, platform = process.platform): DescribedError {
  if (!(error instanceof BridgeCommandError)) {
    return { message: `Unexpected error: ${error instanceof Error ? error.message : String(error)}`, actions: [] };
  }
  const details = error.details;
  switch (error.code) {
    case 'SPAWN_FAILED':
      return {
        message: `The Python interpreter "${pythonPath}" could not be started (${String(details.errno ?? error.message)}). `
          + 'Set px4Gcs.pythonPath to a Python 3.9+ interpreter with pymavlink and pyserial'
          + `${platform === 'win32' ? ' (on Windows this is usually "python")' : ''}, then run the doctor.`,
        actions: [OPEN_PYTHON_SETTING, RUN_DOCTOR],
      };
    case 'MISSING_MODULE':
      return {
        message: `${error.message}. Install it with: "${pythonPath}" -m pip install ${PIP_REQUIREMENTS}`,
        actions: [RUN_DOCTOR, OPEN_PYTHON_SETTING],
      };
    case 'PORT_BUSY': {
      const owner = details.owner as LeaseOwner | null | undefined;
      const device = owner?.device ? ` ${owner.device}` : '';
      return owner
        ? { message: `The port${device} is in use by ${ownerText(owner)}`, actions: [] }
        : { message: `${error.message}: another program has the port open.`, actions: [] };
    }
    case 'PERMISSION_DENIED':
      return {
        message: platform === 'linux'
          ? `${error.message}. Add your user to the dialout group (sudo usermod -aG dialout $USER), then log in again.`
          : `${error.message}.`,
        actions: [],
      };
    case 'PORT_NOT_FOUND':
      return { message: `${error.message}.`, actions: [OPEN_SERIAL_SETTING] };
    case 'NO_HEARTBEAT': {
      const bauds = Array.isArray(details.baudsTried) ? details.baudsTried.join(', ') : '';
      return {
        message: bauds
          ? `No MAVLink heartbeat; listened at ${bauds} baud. Check the cable, the baud rate and that MAVLink runs on this port.`
          : 'No MAVLink heartbeat on the UDP port. Check that the vehicle sends to this address.',
        actions: [bauds ? OPEN_SERIAL_SETTING : OPEN_UDP_SETTING],
      };
    }
    case 'BRIDGE_EXITED': {
      const tail = Array.isArray(details.stderr) && details.stderr.length > 0 ? ` Last output: ${details.stderr.join(' | ')}` : '';
      const signal = typeof details.signal === 'string' ? `, signal ${details.signal}` : '';
      return {
        message: `The MAVLink sidecar stopped (exit code ${String(details.code ?? 'none')}${signal}).${tail}`,
        actions: [RUN_DOCTOR],
      };
    }
    case 'PROTOCOL_MISMATCH':
      return { message: `${error.message}. Reinstall the extension.`, actions: [RUN_DOCTOR] };
    default:
      return { message: error.message, actions: [] };
  }
}

/** Show the message with its buttons; a chosen button runs its command. */
export async function showDescribedError(described: DescribedError, prefix = '1KW-Px4-GCS: '): Promise<void> {
  const choice = await vscode.window.showErrorMessage(`${prefix}${described.message}`,
    ...described.actions.map((a) => a.title));
  const action = described.actions.find((a) => a.title === choice);
  if (action) await vscode.commands.executeCommand(action.command, ...(action.args ?? []));
}
