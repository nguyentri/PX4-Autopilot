import * as vscode from 'vscode';

/**
 * TypeScript contract interfaces for the PX4/NuttX firmware workspace.
 */

export interface Diagnostic {
  level: 'info' | 'warning' | 'error';
  code: string;
  message: string;
  path?: string;
}

export interface OperationResult<T = any> {
  protocolVersion: number;
  operationId: string;
  status: 'ok' | 'blocked' | 'failed' | 'cancelled';
  data: T;
  diagnostics: Diagnostic[];
  childExitCode: number | null;
  receiptPath: string | null;
}

export type FirmwareOperation = 'build' | 'load' | 'debug' | 'console';

export interface OperationOptions {
  cancellationToken?: vscode.CancellationToken;
  onOutput?: (chunk: string, stream: 'stdout' | 'stderr') => void;
  env?: NodeJS.ProcessEnv;
  lease?: ProbeLease;
}

export interface ProbeLease {
  leaseToken: string;
  serial: string;
}

export interface ConsoleHandoff {
  ok: boolean;
  lease?: {
    readonly lease: ProbeLease;
    release(): Promise<void>;
  };
}

export interface FirmwareSelection {
  schemaVersion: number;
  id: string;
  board: 'rdk-rzv2h' | 'evk-ra8p1' | 'fpb-ra8e1';
  core: 'cr8_0' | 'cr8_1' | 'cm33' | 'cm85' | 'multicore';
  build: {
    family: 'px4' | 'nuttx' | 'multicore';
    target?: string;
    config?: string;
    mode: 'incremental' | 'clean';
  };
  load?: {
    recipe: string;
  };
  debug?: {
    mode: 'attach' | 'load-and-debug';
  };
  group?: string;
}

export interface CoreCapability {
  core: string;
  jlinkDevice: string;
  buildAvailable: boolean;
  loadAvailable: boolean;
  debugAvailable: boolean;
  qualification: 'stub' | 'source-audited' | 'build-clean' | 'bounded-on-target' | 'production';
  supportedFamilies: ('px4' | 'nuttx')[];
  remediation: string | null;
  reasons: string[];
  console?: ConsoleTransport;
}

export interface BoardCapability {
  id: string;
  name: string;
  soc: string;
  cores: Record<string, CoreCapability>;
}

export interface CatalogData {
  px4Targets: Array<{ target: string; board: string; core: string; family: string; file: string }>;
  nuttxConfigs: Record<string, Array<{ config: string; board: string; core: string; family: string; directory: string }>>;
  devices: Record<string, BoardCapability>;
  groups: Record<string, GroupMetadata>;
  counts: { px4: number; rzv2hNuttx: number; ra8p1Nuttx: number };
}

export type ConsoleTransport = 'rtt' | 'rtt-output' | 'sci4' | 'sci5' | 'sci9' | 'scif0' | 'uart' | 'none';

export interface GroupMember {
  core: string;
  family: 'px4' | 'nuttx';
  target?: string;
  config?: string;
}

export interface GroupMetadata {
  id?: string;
  name?: string;
  board: string;
  family?: 'px4' | 'nuttx' | 'multicore';
  description?: string;
  loadRecipe?: string;
  definitionSha256?: string;
  members: GroupMember[];
  console?: Record<string, ConsoleTransport>;
}

export interface SelectionCapabilities {
  build: boolean;
  load: boolean;
  debug: boolean;
  console: boolean;
  reasons: string[];
  groupMeta?: GroupMetadata;
  coreCapabilities?: Record<string, CoreCapability>;
}

export interface DoctorData {
  tools: Record<string, { ok: boolean; info?: string; path?: string; remediation?: string }>;
  probes: Array<{ usbDevice: string; product: string; serial: string }>;
  environment: { leakedToolchainVars: string[] };
  submodules: { nuttxInitialized: boolean };
  readiness?: { build: boolean; load: boolean; debug: boolean; console: boolean };
}

export interface ArtifactItem {
  path: string;
  sha256: string;
  size: number;
  core?: string;
  entryPoint?: string | null;
  rttAddress?: string | null;
}

export interface ArtifactReceipt {
  schemaVersion: number;
  receiptId: string;
  timestamp: string;
  family: 'px4' | 'nuttx' | 'multicore';
  board: string;
  core: string;
  selectionId: string;
  target?: string | null;
  config?: string | null;
  gitRevision: string;
  gitDirty: boolean;
  compiler: string;
  artifacts: ArtifactItem[];
  status: 'provisional' | 'committed' | 'failed' | 'cancelled';
  group?: string | null;
  groupDefinitionSha256?: string | null;
}
