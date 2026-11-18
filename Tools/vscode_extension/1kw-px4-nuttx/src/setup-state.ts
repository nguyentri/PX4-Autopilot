import { FirmwareSelection, PreparedPairState, SavedFirmwareSetup } from './types';

export interface FolderState {
  schemaVersion: 2;
  revision: number;
  selection?: FirmwareSelection;
  selectedProbeSerial?: string;
  selectedCore?: string;
  receipts: Record<string, { path: string; receiptId?: string }>;
  imageAssignments: Record<string, PreparedPairState>;
  setups: Record<string, SavedFirmwareSetup>;
  activeSetupId?: string;
}

export const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value));
const forbiddenKeys = new Set(['__proto__', 'prototype', 'constructor']);
const object = (v: any): v is Record<string, any> => {
  if (!v || typeof v !== 'object' || Array.isArray(v)) { return false; }
  try {
    const prototype = Object.getPrototypeOf(v);
    return (prototype === Object.prototype || prototype === null)
      && Reflect.ownKeys(v).every((key) => typeof key === 'string' && !forbiddenKeys.has(key)
        && 'value' in Object.getOwnPropertyDescriptor(v, key)!);
  } catch {
    return false;
  }
};
const own = (v: Record<string, any>, key: string): boolean => Object.prototype.hasOwnProperty.call(v, key);
const optional = (v: Record<string, any>, key: string, valid: (value: any) => boolean): boolean =>
  !own(v, key) || v[key] === undefined || valid(v[key]);
const text = (v: any, max = 8192): v is string => typeof v === 'string' && v.length <= max && !/[\x00-\x1f\x7f]/.test(v);
const identifier = (v: any, max = 256): v is string => text(v, max) && v.length > 0;
const local = (v: any): boolean => text(v) && !v.includes('://');
const uint = (v: any): boolean => Number.isSafeInteger(v) && v >= 0;
const digest = (v: any): boolean => typeof v === 'string' && /^[a-fA-F0-9]{64}$/.test(v);
const uuid = (v: any): boolean => typeof v === 'string'
  && /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i.test(v);
const core = (v: any): boolean => ['cr8_0', 'cr8_1'].includes(v);

function coreMap(v: any, valid: (value: any, key: string) => boolean): boolean {
  return object(v) && Object.entries(v).every(([key, value]) => core(key) && valid(value, key));
}

export function validSelection(v: any): v is FirmwareSelection {
  return object(v) && v.schemaVersion === 1 && identifier(v.id)
    && ['rdk-rzv2h', 'evk-ra8p1', 'fpb-ra8e1'].includes(v.board)
    && ['cr8_0', 'cr8_1', 'cm33', 'cm85', 'multicore'].includes(v.core)
    && object(v.build) && ['px4', 'nuttx', 'multicore'].includes(v.build.family)
    && ['clean', 'incremental'].includes(v.build.mode)
    && (v.group === undefined || identifier(v.group))
    && (v.build.target === undefined || text(v.build.target, 256))
    && (v.build.config === undefined || text(v.build.config, 256));
}

function source(v: any): boolean {
  if (!object(v)) { return false; }
  if (['build-receipt', 'prepared-receipt'].includes(v.kind)) {
    return local(v.receiptPath) && core(v.artifactCore);
  }
  return ['file', 'folder'].includes(v.kind) && local(v.path) && object(v.declaration)
    && core(v.declaration.core) && ['px4', 'nuttx'].includes(v.declaration.family)
    && optional(v.declaration, 'target', (value) => text(value, 256))
    && optional(v.declaration, 'config', (value) => text(value, 256))
    && (v.kind !== 'folder' || local(v.relativePath));
}

function sources(v: any): boolean {
  return coreMap(v, (value, key) => source(value) && (value.declaration?.core !== undefined
    ? value.declaration.core === key
    : value.artifactCore === key));
}

function observation(v: any): boolean {
  return object(v) && local(v.path) && uint(v.size)
    && (digest(v.sha256) || (v.sha256 === 'missing' && v.size === 0 && v.mtimeNs === '0'))
    && typeof v.mtimeNs === 'string' && /^\d+$/.test(v.mtimeNs);
}

function validPending(v: any): boolean {
  return object(v) && object(v.request) && v.request.schemaVersion === 1
    && uuid(v.request.requestId) && validSelection(v.request.selection)
    && sources(v.request.sources) && digest(v.sourceDigest);
}

function validPrepared(v: any): boolean {
  return object(v) && local(v.receiptPath) && text(v.receiptId, 256)
    && digest(v.receiptSha256) && digest(v.groupDefinitionSha256)
    && optional(v, 'pairSha256', digest)
    && Array.isArray(v.artifacts) && v.artifacts.length <= 2
    && new Set(v.artifacts.map((artifact: any) => artifact?.core)).size === v.artifacts.length
    && v.artifacts.every((artifact: any) => object(artifact) && local(artifact.path)
      && digest(artifact.sha256) && uint(artifact.size) && core(artifact.core));
}

export function validPair(v: any): v is PreparedPairState {
  return object(v) && uint(v.generation) && sources(v.sources)
    && optional(v, 'pending', validPending)
    && optional(v, 'prepared', validPrepared)
    && optional(v, 'validationError', text)
    && optional(v, 'acknowledged', (value) => coreMap(value, (entry) => text(entry)))
    && optional(v, 'sourceChanges', (value) => coreMap(value, observation))
    && optional(v, 'history', (value) => object(value) && typeof value.verified === 'boolean'
      && text(value.message) && optional(value, 'timestamp', text));
}

/** Decode without mutating or discarding a malformed/newer stored record. */
export function decodeFolderState(raw: unknown, legacy: unknown): { state: FolderState; error?: string; canonical: boolean } {
  const empty: FolderState = { schemaVersion: 2, revision: 0, receipts: {}, imageAssignments: {}, setups: {} };
  const hasCanonical = raw !== undefined;
  const input: any = hasCanonical ? raw : legacy;
  if (input === undefined) { return { state: empty, canonical: false }; }
  const fail = () => ({ state: empty, canonical: hasCanonical, error: 'Saved firmware state is unavailable: unsupported or malformed format. The stored record was preserved.' });
  if (!object(input) || (hasCanonical ? input.schemaVersion !== 2 : own(input, 'schemaVersion') && input.schemaVersion !== 1)
    || !optional(input, 'selection', validSelection)
    || !optional(input, 'selectedProbeSerial', (value) => text(value, 256))
    || !optional(input, 'selectedCore', (value) => text(value, 64))) { return fail(); }
  for (const key of ['receipts', 'imageAssignments', 'setups']) {
    if (own(input, key) && input[key] !== undefined
      && (!object(input[key]) || Object.keys(input[key]).length > 1024)) { return fail(); }
  }
  const receipts = own(input, 'receipts') ? input.receipts : undefined;
  const assignments = own(input, 'imageAssignments') ? input.imageAssignments : undefined;
  const setups = own(input, 'setups') ? input.setups : undefined;
  if (receipts !== undefined && Object.entries(receipts).some(([id, receipt]: [string, any]) =>
    !identifier(id) || !object(receipt) || !local(receipt.path)
      || !optional(receipt, 'receiptId', (value) => text(value, 256)))) { return fail(); }
  if (assignments !== undefined && Object.entries(assignments).some(([id, pair]) => !identifier(id) || !validPair(pair))) { return fail(); }
  if (hasCanonical && (!uint(input.revision) || Object.entries(setups || {}).some(([id, s]: [string, any]) =>
    !object(s) || s.id !== id || !identifier(id) || !text(s.name, 128) || !s.name.trim()
    || !validSelection(s.selection) || !s.selection.group || !optional(s, 'selectedCore', core) || (s.pair !== undefined && !validPair(s.pair))
    || (s.consoleDevices !== undefined && (!coreMap(s.consoleDevices, local)))))) { return fail(); }
  if (!hasCanonical && (setups !== undefined || own(input, 'activeSetupId') || own(input, 'revision'))) { return fail(); }
  if (own(input, 'activeSetupId') && input.activeSetupId !== undefined
    && (!identifier(input.activeSetupId) || !setups || !own(setups, input.activeSetupId))) { return fail(); }
  if (input.activeSetupId && (!input.selection || JSON.stringify(input.selection) !== JSON.stringify(setups[input.activeSetupId].selection))) { return fail(); }
  try {
    return { state: { ...empty, ...copy(input), schemaVersion: 2 }, canonical: hasCanonical };
  } catch {
    return fail();
  }
}
