import * as vscode from 'vscode';

/** Every `px4Gcs.*` setting, typed. Defaults mirror package.json. */
export interface GcsSettings {
  pythonPath: string;
  transport: 'serial' | 'udp';
  serialPort: string;
  serialBaud: number;
  baudCandidates: number[];
  udpHost: string;
  udpPort: number;
  controlEnabled: boolean;
  metadataPath: string;
  recordingDirectory: string;
}

const SECTION = 'px4Gcs';

function positiveInt(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : fallback;
}

function text(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value.trim() : fallback;
}

export function readGcsSettings(): GcsSettings {
  const c = vscode.workspace.getConfiguration(SECTION);
  const candidates = c.get<unknown>('serial.baudCandidates');
  const bauds = Array.isArray(candidates)
    ? candidates.filter((b): b is number => typeof b === 'number' && Number.isInteger(b) && b > 0)
    : [];
  return {
    pythonPath: text(c.get('pythonPath'), 'python3') || 'python3',
    transport: c.get('transport') === 'udp' ? 'udp' : 'serial',
    serialPort: text(c.get('serial.port'), ''),
    serialBaud: positiveInt(c.get('serial.baud'), 115200),
    baudCandidates: bauds.length > 0 ? bauds : [115200, 57600],
    udpHost: text(c.get('udp.host'), '127.0.0.1') || '127.0.0.1',
    udpPort: positiveInt(c.get('udp.port'), 14550),
    controlEnabled: c.get('control.enabled') !== false,
    metadataPath: text(c.get('parameters.metadataPath'), ''),
    recordingDirectory: text(c.get('recording.directory'), ''),
  };
}
