// "Differs from build default": the vehicle value against the metadata
// default of the loaded build. A board start-up script overrides some
// defaults (MAV_0_RATE is 1200 in the metadata and 4000 on the demo image), so
// this is not "changed by the operator". Pure; no `vscode` import.
import { ParamMeta } from './parameter-metadata';

/** Undefined when there is nothing to compare (no default, volatile, no value). */
export function differsFromDefault(value: number | null, type: string, meta: ParamMeta | undefined): boolean | undefined {
  if (!meta || meta.volatile || meta.default === undefined || value === null || !Number.isFinite(value)) return undefined;
  if (type !== 'REAL32') return Math.trunc(value) !== Math.trunc(meta.default);
  if (meta.decimalPlaces !== undefined) {
    return Math.abs(value - meta.default) > 0.5 * 10 ** -meta.decimalPlaces + 1e-9;
  }
  return Math.fround(value) !== Math.fround(meta.default);
}
