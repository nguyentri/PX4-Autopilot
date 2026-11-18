// Which parameter edits need a modal confirmation, and why. The value must
// parse for the parameter's type; a name starting with `_` is never editable.
// Pure; no `vscode` import. The family list is a reviewed judgement, not a
// PX4 classification: a family a later PX4 version adds is not in it until
// the list is reviewed again (rebootRequired, range and armed still apply).
import { ParamMeta } from './parameter-metadata';

/** Safety-relevant parameter families, by class, with the reason the modal shows. */
export const SAFETY_FAMILIES: readonly { cls: string; reason: string; families: readonly string[] }[] = [
  { cls: 'protections', reason: 'changes an arming check, failsafe or protection',
    families: ['CBRK', 'COM', 'NAV', 'GF', 'FD', 'BAT', 'RTL', 'MAN'] },
  { cls: 'actuators', reason: 'changes what drives the actuators', families: ['CA', 'PWM', 'DSHOT', 'HIL', 'UAVCAN'] },
  { cls: 'link and system', reason: 'can cut this link or change the system identity', families: ['MAV', 'SER', 'SYS'] },
  { cls: 'radio', reason: 'changes the radio mapping', families: ['RC'] },
  { cls: 'sensors and estimator', reason: 'changes which sensor data the estimator uses',
    families: ['SENS', 'CAL', 'TC', 'EKF2', 'LPE', 'ATT'] },
];

/** The family class of a name: it starts with the family and the next character is a digit or `_`. */
export function safetyClass(name: string): { cls: string; family: string; reason: string } | undefined {
  for (const entry of SAFETY_FAMILIES) {
    for (const family of entry.families) {
      if (name.startsWith(family) && /^[0-9_]$/.test(name.charAt(family.length))) {
        return { cls: entry.cls, family, reason: entry.reason };
      }
    }
  }
  return undefined;
}

const INT_RANGES: Record<string, [number, number]> = {
  UINT8: [0, 255], INT8: [-128, 127], UINT16: [0, 65535], INT16: [-32768, 32767],
  UINT32: [0, 4294967295], INT32: [-2147483648, 2147483647],
};

/** Parse the operator's text for a vehicle type; an error message when it does not fit. */
export function parseParamValue(text: string, type: string): { value: number } | { error: string } {
  const trimmed = String(text).trim();
  if (trimmed === '') return { error: 'Enter a value.' };
  const range = INT_RANGES[type];
  if (range) {
    if (!/^[+-]?\d+$/.test(trimmed)) return { error: `${type} needs a whole number.` };
    const value = Number(trimmed);
    if (value < range[0] || value > range[1]) return { error: `${type} holds ${range[0]}..${range[1]}.` };
    return { value };
  }
  if (type === 'REAL32') {
    const value = Number(trimmed);
    if (!Number.isFinite(value) || !/^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/i.test(trimmed)) {
      return { error: 'Enter a decimal number.' };
    }
    if (Math.abs(value) > 3.4028234663852886e38) return { error: 'Out of the 32-bit float range.' };
    return { value };
  }
  return { error: `Unsupported parameter type ${type}.` };
}

export interface EditCheck {
  name: string;
  /** The vehicle's type for this parameter. */
  type: string;
  value: number;
  armed: boolean | null;
  metadataLoaded: boolean;
  meta: ParamMeta | undefined;
}

/** Reasons the edit needs a modal; empty when it applies directly. */
export function editReasons(check: EditCheck): string[] {
  const reasons: string[] = [];
  const { meta } = check;
  if (!check.metadataLoaded) reasons.push('no parameter metadata is loaded');
  else if (!meta) reasons.push('the parameter is not in the loaded metadata');
  else if (meta.type !== check.type) reasons.push(`the metadata type ${meta.type} differs from the vehicle type ${check.type}`);
  if (meta?.min !== undefined && check.value < meta.min) reasons.push(`the value is below the minimum ${meta.min}`);
  if (meta?.max !== undefined && check.value > meta.max) reasons.push(`the value is above the maximum ${meta.max}`);
  if (meta?.rebootRequired) reasons.push('it takes effect only after a reboot');
  const family = safetyClass(check.name);
  if (family) reasons.push(`${family.cls}: ${family.reason} (${family.family})`);
  if (check.armed !== false) reasons.push(check.armed ? 'the vehicle is armed' : 'the armed state is unknown');
  return reasons;
}

/** Why a name can never be edited here, or undefined. */
export function nameRefusal(name: string): string | undefined {
  return name.startsWith('_') ? `${name} is an internal parameter and is never written.` : undefined;
}
