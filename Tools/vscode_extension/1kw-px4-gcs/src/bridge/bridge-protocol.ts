// TypeScript mirror of schemas/bridge-protocol.schema.json (protocol version 1).
// tests/connection-tests.js checks that the name lists below equal the schema enums.

export const PROTOCOL_VERSION = 1;

export const COMMAND_NAMES = [
  'hello', 'doctor', 'list_ports', 'connect', 'disconnect', 'cancel',
  'param_list', 'param_read', 'param_set',
  'arm', 'disarm', 'set_mode', 'reboot',
  'stream_request', 'stream_release',
  'shell_open', 'shell_write', 'shell_close',
  'inspector_subscribe', 'inspector_unsubscribe',
  'log_list', 'log_download', 'record_start', 'record_stop',
] as const;

export const EVENT_NAMES = [
  'link', 'heartbeat', 'modes', 'attitude', 'position', 'local_position', 'gps', 'battery', 'vfr',
  'statustext', 'sensors', 'named_value', 'param_progress', 'shell_data', 'inspector',
  'log_progress', 'recording',
] as const;

export const ERROR_CODES = [
  'PORT_BUSY', 'PORT_NOT_FOUND', 'PERMISSION_DENIED', 'NO_HEARTBEAT', 'NOT_CONNECTED', 'TIMEOUT',
  'CANCELLED', 'DENIED', 'BAD_ARGUMENT', 'MISSING_MODULE', 'NOT_IMPLEMENTED', 'INTERNAL',
] as const;

export type CommandName = (typeof COMMAND_NAMES)[number];
export type EventName = (typeof EVENT_NAMES)[number];
export type ErrorCode = (typeof ERROR_CODES)[number];
/** Errors raised by the extension host itself, never sent by the sidecar. */
export type HostErrorCode = 'SPAWN_FAILED' | 'BRIDGE_EXITED' | 'PROTOCOL_MISMATCH';

export interface BridgeErrorBody {
  code: ErrorCode;
  message: string;
  details?: Record<string, unknown>;
}

export interface BridgeReply {
  type: 'reply';
  id: number | null;
  ok: boolean;
  data?: Record<string, unknown>;
  error?: BridgeErrorBody;
}

export interface BridgeEvent<T = Record<string, unknown>> {
  type: 'event';
  name: EventName;
  ts: number;
  data: T;
}

export type LinkState = 'connecting' | 'connected' | 'lost' | 'disconnected';

export interface LinkData {
  state: LinkState;
  transport?: 'serial' | 'udp';
  port?: string;
  baud?: number | null;
  host?: string;
  udpPort?: number;
  systemId?: number;
  componentId?: number;
  autopilot?: number;
  vehicleType?: number;
  foreignFrames?: number;
  badFrames?: number;
  ignoredAcks?: number;
  droppedStatusText?: number;
  droppedNamedValues?: number;
  droppedEvents: number;
}

export interface HeartbeatData {
  armed: boolean;
  mode: string;
  modeKey: string | null;
  mainMode: number;
  subMode: number;
  customMode: number;
  baseMode?: number;
  systemStatus: number;
  vehicleType?: number;
}

/** One row of the sidecar's PX4 mode table (`hello.modes`). */
export interface ModeEntry {
  key: string;
  name: string;
  main: number;
  sub: number;
  needsSticks: boolean;
}

export interface HelloData {
  protocolVersion: number;
  bridgeVersion: string;
  commands: string[];
  modes: ModeEntry[];
}

export interface DoctorData {
  bridgeVersion: string;
  protocolVersion: number;
  python: string;
  pythonExecutable: string;
  platform: string;
  pymavlink: string | null;
  pyserial: string | null;
  missing: string[];
  pythonOk: boolean;
}

export interface SerialPortInfo {
  device: string;
  byId: string | null;
  vid: number | null;
  pid: number | null;
  description: string | null;
  manufacturer: string | null;
  serialNumber: string | null;
  rank: number;
}

/** Arguments of the `connect` command, as the sidecar validates them. */
export type ConnectArgs =
  | { transport: 'udp'; host: string; port: number; controlEnabled: boolean; sessionId: string; probeSeconds?: number }
  | {
    transport: 'serial'; device: string; baudCandidates: number[]; controlEnabled: boolean;
    sessionId: string; probeSeconds?: number;
  };

/** Long commands: the reply may take long, but progress events must keep arriving. */
export const PROGRESS_EVENT: Partial<Record<CommandName, EventName>> = {
  param_list: 'param_progress',
  log_download: 'log_progress',
};
