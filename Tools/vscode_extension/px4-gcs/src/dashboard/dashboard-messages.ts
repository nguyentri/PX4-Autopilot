// The only definition of the messages between the extension host and the
// dashboard webview. Both tsconfigs compile this file, so it imports nothing
// and holds types and plain constants only.

export const TAB_IDS = ['fly', 'parameters', 'console', 'inspector', 'sensors', 'plots', 'track', 'logs'] as const;
export type TabId = (typeof TAB_IDS)[number];

/** Connection state as the dashboard shows it (the controller's state plus the link). */
export type DashboardConnection = 'idle' | 'connecting' | 'connected' | 'lost' | 'disconnecting';

export interface SampleMessage {
  /** Sidecar wall-clock time in seconds. */
  ts: number;
  data: Record<string, unknown>;
}

export interface StatusEntry {
  ts: number;
  severity: number;
  text: string;
}

/** Metadata of one parameter from the loaded build (`parameters.json`). */
export interface ParamMetaView {
  default?: number;
  min?: number;
  max?: number;
  units?: string;
  decimalPlaces?: number;
  increment?: number;
  shortDesc?: string;
  longDesc?: string;
  group?: string;
  values?: { value: number; description: string }[];
  bitmask?: { index: number; description: string }[];
  rebootRequired: boolean;
  volatile: boolean;
  /** Metadata type, set only when it differs from the vehicle's type. */
  typeMismatch?: string;
}

export interface ParamEntry {
  name: string;
  index: number;
  type: string;
  value: number | null;
  meta?: ParamMetaView;
  /** True when the value differs from the build default; absent when not comparable. */
  differs?: boolean;
}

export type ParamsState =
  | { state: 'idle' }
  | { state: 'loading'; received: number; total: number | null }
  | { state: 'done'; params: ParamEntry[]; count: number | null; missing: number[]; metadata: string }
  | { state: 'error'; message: string };

export type ConsoleState =
  | { state: 'closed' }
  | { state: 'open' }
  | { state: 'declined' }
  | { state: 'disabled'; reason: string };

export interface InspectorRow {
  name: string;
  id: number;
  component: number;
  count: number;
  rateHz: number;
  last: Record<string, unknown> | null;
}

/** One row of the sidecar's PX4 mode table. */
export interface ModeView {
  key: string;
  name: string;
  needsSticks: boolean;
}

export type ControlAction = 'arm' | 'disarm' | 'set_mode' | 'reboot';

/** Outcome of a guarded command, as the Fly tab shows it. */
export interface CommandOutcomeView {
  action: ControlAction;
  mode?: string;
  /** refused | declined | accepted | denied | temporarily rejected | failed | timeout | ... */
  result: string;
  message: string;
}

/** Outcome of a parameter edit. */
export interface ParamOutcomeView {
  name: string;
  /** applied | not applied | refused | declined | failed */
  result: string;
  value: number | null;
  message: string;
}

export type ParamFileCommand = 'exportParameters' | 'importParameters';
export type SessionCommand = 'startRecording' | 'stopRecording' | 'openSessionReport';
/** Extension commands the webview may run (each still applies its own checks). */
export type RunnableCommand = 'quickConnect' | 'connect' | 'disconnect' | ParamFileCommand | SessionCommand;

/** One onboard log from LOG_ENTRY. */
export interface LogEntryView {
  id: number;
  size: number;
  /** Unix seconds, null when the vehicle had no clock. */
  timeUtc: number | null;
}

export type LogsState =
  | { state: 'idle' }
  | { state: 'loading' }
  | { state: 'done'; entries: LogEntryView[]; answered: boolean; truncated: boolean }
  | { state: 'error'; message: string };

/** The one running or last finished log download. */
export interface LogTransferView {
  logId: number;
  state: 'running' | 'done' | 'cancelled' | 'failed' | 'refused';
  received: number;
  total: number;
  /** Bytes per second over the transfer so far. */
  rateBps: number;
  message: string;
  path?: string;
}

export interface RecordingView {
  active: boolean;
  path?: string;
  /** Set when a recording stopped: why and how much it holds. */
  reason?: string;
  frames?: number;
}

export interface LinkSummary {
  transport?: string;
  port?: string;
  baud?: number | null;
  host?: string;
  udpPort?: number;
  systemId?: number;
}

/** Host to webview. */
export type HostMessage =
  | {
    type: 'snapshot'; connection: DashboardConnection; link: LinkSummary | null; stale: boolean;
    values: Record<string, SampleMessage>; status: StatusEntry[]; params: ParamsState; console: ConsoleState;
    controlEnabled: boolean; tab?: TabId; modes: ModeView[];
  }
  | { type: 'connection'; connection: DashboardConnection; link: LinkSummary | null; stale: boolean; modes: ModeView[] }
  | { type: 'values'; values: Record<string, SampleMessage>; stale: boolean }
  | { type: 'status'; entries: StatusEntry[] }
  | { type: 'params'; params: ParamsState }
  | { type: 'param_value'; entry: ParamEntry }
  | { type: 'param_result'; outcome: ParamOutcomeView }
  | { type: 'command_result'; outcome: CommandOutcomeView }
  | { type: 'console'; console: ConsoleState }
  | { type: 'shell'; text: string }
  | { type: 'inspector'; messages: InspectorRow[]; unknown: number }
  | { type: 'stream_note'; tab: TabId; message: number; outcome: 'raised' | 'refused'; reason?: string }
  | { type: 'focus'; tab: TabId }
  /** The host store's history (10 Hz, 10 minutes) for the plotted and tracked keys, sent on request. */
  | { type: 'history'; series: Record<string, SampleMessage[]> }
  | { type: 'logs'; logs: LogsState }
  | { type: 'log_transfer'; transfer: LogTransferView | null }
  | { type: 'recording'; recording: RecordingView };

/** Webview to host. */
export type WebviewMessage =
  | { type: 'ready' }
  | { type: 'run'; command: RunnableCommand }
  | { type: 'command'; action: ControlAction; mode?: string }
  | { type: 'param_edit'; name: string; value: string }
  | { type: 'tab'; tab: TabId }
  | { type: 'params_refresh' }
  | { type: 'console_open' }
  | { type: 'console_input'; data: string }
  | { type: 'console_close' }
  | { type: 'copy'; text: string }
  | { type: 'history_request' }
  | { type: 'logs_refresh' }
  | { type: 'log_download'; id: number }
  | { type: 'log_cancel' };

/** Values grey out when the newest sample of a key is older than this. */
export const STALE_AFTER_MS = 2000;
/** Status-log entries kept by the host for replay when the dashboard reopens. */
export const STATUS_LOG_CAPACITY = 500;
/** History the host keeps and the webview mirrors: seconds and samples per second (plan decision D5). */
export const HISTORY_SECONDS = 600;
export const HISTORY_RATE_HZ = 10;
/** Minimum spacing of kept samples; half a millisecond of slack because event times are rounded to 1 ms. */
export const HISTORY_MIN_SPACING_S = 1 / HISTORY_RATE_HZ - 0.0005;
/** Keys whose history the Plots and Track tabs use; `named_value:` is a prefix. */
export const PLOTTED_KEYS = ['attitude', 'position', 'local_position', 'gps', 'battery', 'vfr'] as const;
export const NAMED_VALUE_PREFIX = 'named_value:';
/** Shown when LOG_REQUEST_LIST got no answer while heartbeats kept arriving. */
export const NO_LOGS_TEXT = 'The vehicle reported no logs. PX4 does not answer this request when it has none. '
  + 'On the RDK-RZ/V2H the logger module is not built and storage is RAM-only.';
