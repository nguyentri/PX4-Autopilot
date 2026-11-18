// Parameter metadata from a PX4 build tree (`build/<target>/parameters.json`):
// parsing and the type comparison with the vehicle. Pure; no `vscode` import.

export interface ParamEnumValue {
  value: number;
  description: string;
}

export interface ParamBit {
  index: number;
  description: string;
}

export interface ParamMeta {
  name: string;
  /** Vehicle spelling: REAL32, INT32, ... (the build file says Float, Int32). */
  type: string;
  default?: number;
  min?: number;
  max?: number;
  units?: string;
  decimalPlaces?: number;
  increment?: number;
  shortDesc?: string;
  longDesc?: string;
  group?: string;
  values?: ParamEnumValue[];
  bitmask?: ParamBit[];
  rebootRequired: boolean;
  volatile: boolean;
}

export interface ParameterMetadataSet {
  /** Absolute path of the file. */
  path: string;
  /** Build target, the directory name under `build/`. */
  target: string;
  byName: Map<string, ParamMeta>;
}

/** Build-file type name to the vehicle's MAV_PARAM_TYPE name: Float -> REAL32, Int32 -> INT32. */
export function normalizeParamType(type: string): string {
  const upper = String(type).toUpperCase();
  return upper === 'FLOAT' ? 'REAL32' : upper;
}

function num(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function str(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

/** Parse a `parameters.json` body; throws on a file that is not PX4 metadata. */
export function parseParameterMetadata(text: string, path: string): ParameterMetadataSet {
  const doc = JSON.parse(text) as { parameters?: unknown };
  if (!doc || !Array.isArray(doc.parameters)) throw new Error(`${path} has no "parameters" list`);
  const byName = new Map<string, ParamMeta>();
  for (const raw of doc.parameters as Record<string, unknown>[]) {
    const name = str(raw?.name);
    if (!name) continue;
    const values = Array.isArray(raw.values)
      ? (raw.values as Record<string, unknown>[])
        .filter((v) => num(v.value) !== undefined)
        .map((v) => ({ value: v.value as number, description: String(v.description ?? '') }))
      : undefined;
    const bitmask = Array.isArray(raw.bitmask)
      ? (raw.bitmask as Record<string, unknown>[])
        .filter((b) => num(b.index) !== undefined)
        .map((b) => ({ index: b.index as number, description: String(b.description ?? '') }))
      : undefined;
    byName.set(name, {
      name,
      type: normalizeParamType(String(raw.type ?? '')),
      default: num(raw.default),
      min: num(raw.min),
      max: num(raw.max),
      units: str(raw.units),
      decimalPlaces: num(raw.decimalPlaces),
      increment: num(raw.increment),
      shortDesc: str(raw.shortDesc),
      longDesc: str(raw.longDesc),
      group: str(raw.group),
      values: values && values.length > 0 ? values : undefined,
      bitmask: bitmask && bitmask.length > 0 ? bitmask : undefined,
      rebootRequired: raw.rebootRequired === true,
      volatile: raw.volatile === true,
    });
  }
  const parts = path.split(/[\\/]/);
  return { path, target: parts.length >= 2 ? parts[parts.length - 2] : '', byName };
}

/** "build/renesas_rdk-rzv2h_demo/parameters.json (renesas_rdk-rzv2h_demo)" or "no metadata". */
export function metadataSourceText(set: ParameterMetadataSet | undefined): string {
  return set ? `${set.path} (${set.target})` : 'no metadata';
}
