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

export type FirmwareOperation = 'build' | 'load' | 'debug';

export interface OperationOptions {
  cancellationToken?: vscode.CancellationToken;
  onOutput?: (chunk: string, stream: 'stdout' | 'stderr') => void;
  env?: NodeJS.ProcessEnv;
  lease?: ProbeLease;
  operationInstanceId?: string;
  onProgress?: (event: LoadProgressEvent) => void;
}

export interface LoadProgressEvent {
  eventVersion: 1; operationInstanceId: string; phase: 'load' | 'verify';
  core: 'cr8_0' | 'cr8_1'; state: 'begin' | 'ok' | 'fail' | 'indeterminate'; logPath: string;
}

export interface ProbeLease {
  leaseToken: string;
  serial: string;
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
  capabilities?: { importImages?: number; receiptVersions?: number[]; preparedIdentity?: number;
    strictLoadedIdentity?: number; progressEvents?: number; targetHistory?: number };
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
  reasons: string[];
  groupMeta?: GroupMetadata;
  coreCapabilities?: Record<string, CoreCapability>;
}

export interface DoctorData {
  importPrerequisites?: { ready: boolean; jsonschema: boolean; readelf: string | null; remediation: string };
  targetHistory?: { state: string; recoveryRequired: boolean; verifiedPair?: {
    pairSha256: string; groupDefinitionSha256: string; artifactDigests: Record<R8Core, string>; timestamp: string;
  } | null };
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
  provenance?: ImageProvenance;
  sourceObservation?: SourceObservation;
  member?: GroupMember;
  checks?: { bytes: string; address: string; startup: string; identity: string; hardwareQualified: false };
}

export interface ArtifactReceiptV1 {
  schemaVersion: 1;
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

export interface ImageProvenance {
  evidence: 'receipt-reported' | 'developer-declared' | 'unknown';
  sourceReceiptId: string | null;
  reportedGitRevision: string | null;
  reportedGitDirty: boolean | null;
  reportedCompiler: string | null;
}

export interface SourceObservation {
  path: string; sha256: string; size: number; mtimeNs: string;
}

export interface ArtifactReceiptV2 extends Omit<ArtifactReceiptV1, 'schemaVersion' | 'gitRevision' | 'gitDirty' | 'compiler'> {
  schemaVersion: 2;
  operation: 'import-images';
  requestId: string;
  gitRevision: string | null;
  gitDirty: boolean | null;
  compiler: string | null;
  provenance: ImageProvenance;
}
export type ArtifactReceipt = ArtifactReceiptV1 | ArtifactReceiptV2;
export type R8Core = 'cr8_0' | 'cr8_1';
export type ImageSource =
  | { kind: 'file'; path: string; declaration: GroupMember }
  | { kind: 'folder'; path: string; relativePath: string; declaration: GroupMember }
  | { kind: 'build-receipt' | 'prepared-receipt'; receiptPath: string; artifactCore: R8Core };
export interface FirmwareImport {
  schemaVersion: 1; requestId: string; selection: FirmwareSelection; sources: Partial<Record<R8Core, ImageSource>>;
}
export interface ImportImagesData {
  preparationState: 'partial' | 'ready'; requestId: string; receiptId: string;
  groupDefinitionSha256: string; artifacts: ArtifactItem[];
}

export interface PreparedPairState {
  generation: number;
  sources: Partial<Record<R8Core, ImageSource>>;
  pending?: { request: FirmwareImport; sourceDigest: string };
  prepared?: { receiptPath: string; receiptId: string; receiptSha256: string;
    groupDefinitionSha256: string; artifacts: ArtifactItem[]; pairSha256?: string };
  acknowledged?: Partial<Record<R8Core, string>>;
  sourceChanges?: Partial<Record<R8Core, SourceObservation>>;
  validationError?: string;
  history?: { verified: boolean; message: string; timestamp?: string };
}

export interface PreparedExecutionRequest {
  setupToken?: SetupOperationToken;
  workflowOwner?: symbol;
  workflowCancellation?: vscode.CancellationToken;
  selection: FirmwareSelection; selectionPath: string; receiptPath: string; receiptId: string;
  pairGeneration: number; groupDefinitionSha256: string; pairSha256: string;
  operationInstanceId: string; artifactDigests: Record<R8Core, string>; serial: string;
}

export interface SavedFirmwareSetup {
  id: string;
  name: string;
  selection: FirmwareSelection;
  selectedCore?: string;
  pair?: PreparedPairState;
  consoleDevices?: Record<string, string>;
}

export interface SetupOperationToken {
  setupId?: string;
  pairGeneration?: number;
  revision: number;
  selectionIdentity: string;
  definition?: string;
  probe: string;
  core?: string;
}
