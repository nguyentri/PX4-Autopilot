// Turns settings, the remembered link and the sidecar's port list into
// `connect` arguments. Asks with a QuickPick only when the choice is open.
import { randomUUID } from 'crypto';
import * as vscode from 'vscode';
import { BridgeClient, BridgeCommandError } from '../bridge/bridge-client';
import { ConnectArgs, SerialPortInfo } from '../bridge/bridge-protocol';
import { GcsSettings } from '../gcs-settings';

export const REMEMBERED_LINK_KEY = 'px4Gcs.lastSerialLink';
const MAX_BAUDS = 8;

export interface RememberedLink {
  device: string;
  baud: number;
}

/** Remembered baud first, then the setting, then the candidates; duplicates and invalid rates dropped. */
export function baudOrder(settings: GcsSettings, remembered: number | undefined): number[] {
  const out: number[] = [];
  for (const baud of [remembered, settings.serialBaud, ...settings.baudCandidates]) {
    if (typeof baud === 'number' && Number.isInteger(baud) && baud >= 1200 && baud <= 4000000 && !out.includes(baud)) {
      out.push(baud);
    }
  }
  return out.slice(0, MAX_BAUDS);
}

export function isLoopbackHost(host: string): boolean {
  const h = host.trim().toLowerCase();
  return h === 'localhost' || h === '::1' || /^127(\.\d{1,3}){3}$/.test(h);
}

/** A window-stable id written into the serial lease so other owners can name this one. */
export function sessionId(): string {
  const id = (vscode.env as { sessionId?: string }).sessionId;
  return id ? `px4-gcs-${id}` : `px4-gcs-${randomUUID()}`;
}

/** Non-loopback bind: a modal whose only action is "Bind"; dismissing it (the default) declines. */
export async function confirmUdpBind(host: string, port: number): Promise<boolean> {
  if (isLoopbackHost(host)) return true;
  const choice = await vscode.window.showWarningMessage(
    `Bind UDP ${host}:${port}? Any host that can reach this address can send MAVLink to this station.`,
    { modal: true }, 'Bind');
  return choice === 'Bind';
}

export function udpArgs(settings: GcsSettings): ConnectArgs {
  return { transport: 'udp', host: settings.udpHost, port: settings.udpPort,
    controlEnabled: settings.controlEnabled, sessionId: sessionId() };
}

function portLabel(port: SerialPortInfo): vscode.QuickPickItem & { device: string } {
  const what = [port.manufacturer, port.description].filter(Boolean).join(' ');
  return { label: port.device, description: what || undefined, detail: port.byId ?? undefined, device: port.device };
}

async function listPorts(client: BridgeClient): Promise<SerialPortInfo[]> {
  const data = await client.request<{ ports: SerialPortInfo[] }>('list_ports');
  return data.ports;
}

/**
 * Port choice: the `serial.port` setting, else the remembered port when it is
 * still present, else the single preferred (FTDI/PX4) port or the only port,
 * else a QuickPick. `alwaysAsk` (the Connect command) skips straight to the pick.
 */
export async function chooseSerialPort(client: BridgeClient, settings: GcsSettings,
  remembered: RememberedLink | undefined, alwaysAsk: boolean): Promise<string | undefined> {
  if (settings.serialPort && !alwaysAsk) return settings.serialPort;
  const ports = await listPorts(client);
  if (ports.length === 0) {
    throw new BridgeCommandError('PORT_NOT_FOUND', 'No serial port found; plug in the telemetry cable or set px4Gcs.serial.port');
  }
  if (!alwaysAsk) {
    if (remembered && ports.some((p) => p.device === remembered.device || p.byId === remembered.device)) {
      return remembered.device;
    }
    const preferred = ports.filter((p) => p.rank > 0);
    if (preferred.length === 1) return preferred[0].device;
    if (ports.length === 1) return ports[0].device;
  }
  const pick = await vscode.window.showQuickPick(ports.map(portLabel), {
    title: 'Px4-GCS: serial port', placeHolder: 'Port the vehicle telemetry is on',
  });
  return pick?.device;
}

export async function serialArgs(client: BridgeClient, settings: GcsSettings,
  remembered: RememberedLink | undefined, alwaysAsk: boolean): Promise<ConnectArgs | undefined> {
  const device = await chooseSerialPort(client, settings, remembered, alwaysAsk);
  if (!device) return undefined;
  const rememberedBaud = remembered && remembered.device === device ? remembered.baud : undefined;
  return { transport: 'serial', device, baudCandidates: baudOrder(settings, rememberedBaud),
    controlEnabled: settings.controlEnabled, sessionId: sessionId() };
}

/** The Connect command: pick serial or UDP first. */
export async function pickTransport(settings: GcsSettings): Promise<'serial' | 'udp' | undefined> {
  const items: (vscode.QuickPickItem & { value: 'serial' | 'udp' })[] = [
    { label: 'Serial', description: settings.serialPort || 'choose a port', value: 'serial' },
    { label: 'UDP', description: `${settings.udpHost}:${settings.udpPort}`, value: 'udp' },
  ];
  if (settings.transport === 'udp') items.reverse();
  const pick = await vscode.window.showQuickPick(items, { title: 'Px4-GCS: connect over' });
  return pick?.value;
}
