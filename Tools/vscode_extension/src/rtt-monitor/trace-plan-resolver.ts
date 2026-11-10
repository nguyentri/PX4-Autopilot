import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { R8Core } from '../types';
import { TracePlan } from './rtt-trace-session';

/** `dual` serves both RTT consoles from one probe; `switch` traces one RTT core at a time. */
export type RttMode = 'dual' | 'switch';

/** Host TCP ports of the serial relays, one per core, next to the RTT bridge ports. */
export const SERIAL_RELAY_PORTS: Record<R8Core, number> = { cr8_0: 19041, cr8_1: 19042 };

const CORES: R8Core[] = ['cr8_0', 'cr8_1'];

export function rttMode(): RttMode {
  return vscode.workspace.getConfiguration('px4Nuttx.rtt').get<string>('mode', 'dual') === 'switch' ? 'switch' : 'dual';
}

/**
 * Chooses what to trace from each core's console transport. Two RTT cores
 * trace together in `dual` mode, else the requested (or first) RTT core. A core
 * whose console is a host UART joins as a serial pane next to the RTT core;
 * with no RTT core, the requested (or first) serial core is traced alone.
 */
export function resolveTracePlan(transport: (core: R8Core) => string, mode: RttMode, core?: R8Core): TracePlan | undefined {
  const rtt = CORES.filter((key) => transport(key) === 'rtt');
  const serial = CORES.filter((key) => /^(sci|uart)/.test(transport(key)));
  if (rtt.length === 2) { return { rtt: mode === 'dual' ? 'dual' : (core || 'cr8_0') }; }
  if (rtt.length === 1) { return { rtt: rtt[0], serial: serial[0] }; }
  if (serial.length) { return { serial: core && serial.includes(core) ? core : serial[0] }; }
  return undefined;
}

/** Stable host UART names; by-id survives re-enumeration across USB replugs. */
export function serialCandidates(directory = '/dev/serial/by-id'): string[] {
  try { return fs.readdirSync(directory).map((name) => path.join(directory, name)).sort(); }
  catch { return []; }
}

/** The core's saved console device, or one the user picks (and the setup keeps). */
export async function consoleDeviceFor(saved: string | undefined, save: (device: string) => Promise<void>,
  name: string): Promise<string | undefined> {
  if (saved) { return saved; }
  const candidates = serialCandidates();
  const picked = candidates.length
    ? (await vscode.window.showQuickPick(candidates.map((device) => ({ label: path.basename(device), description: device, device })),
      { placeHolder: `Choose the host UART wired to the ${name} console` }))?.device
    : await vscode.window.showInputBox({ prompt: `Host serial device for the ${name} console`, value: '/dev/ttyUSB0' });
  if (!picked) { return undefined; }
  await save(picked);
  return picked;
}
