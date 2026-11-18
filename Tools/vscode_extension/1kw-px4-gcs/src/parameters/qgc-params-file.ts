// QGroundControl `.params` files: `#` header lines, then tab-separated
// `vehicleId componentId name value type` with the MAV_PARAM_TYPE number.
// Floats are written with 9 significant digits, enough to round-trip a
// 32-bit float. Pure; no `vscode` import.

export const PARAM_TYPE_IDS: Record<string, number> = {
  UINT8: 1, INT8: 2, UINT16: 3, INT16: 4, UINT32: 5, INT32: 6, REAL32: 9,
};

export function paramTypeName(id: number): string | undefined {
  return Object.keys(PARAM_TYPE_IDS).find((name) => PARAM_TYPE_IDS[name] === id);
}

export interface ParamsFileRow {
  line: number;
  systemId: number;
  componentId: number;
  name: string;
  value: number;
  /** Type name (REAL32, INT32, ...). */
  type: string;
}

export interface ParsedParamsFile {
  rows: ParamsFileRow[];
  /** Lines that are neither comments nor valid rows, with the reason. */
  errors: { line: number; reason: string }[];
}

export function formatParamFileValue(value: number, type: string): string {
  return type === 'REAL32' ? String(Number(Math.fround(value).toPrecision(9))) : String(Math.trunc(value));
}

/** Equal as the vehicle stores them: 32-bit floats compared after rounding, integers exactly. */
export function sameParamValue(a: number, b: number, type: string): boolean {
  return type === 'REAL32' ? Math.fround(a) === Math.fround(b) : Math.trunc(a) === Math.trunc(b);
}

export function formatParamsFile(rows: { name: string; value: number; type: string }[], systemId: number,
  componentId: number, header: string[] = []): string {
  const lines = [
    `# Onboard parameters for Vehicle ${systemId}`,
    '#',
    ...header.map((line) => `# ${line}`),
    '#',
    '# Vehicle-Id Component-Id Name Value Type',
  ];
  for (const row of [...rows].sort((a, b) => a.name.localeCompare(b.name))) {
    const typeId = PARAM_TYPE_IDS[row.type];
    if (typeId === undefined) continue;
    lines.push([systemId, componentId, row.name, formatParamFileValue(row.value, row.type), typeId].join('\t'));
  }
  return `${lines.join('\n')}\n`;
}

export function parseParamsFile(text: string): ParsedParamsFile {
  const rows: ParamsFileRow[] = [];
  const errors: { line: number; reason: string }[] = [];
  text.split(/\r?\n/).forEach((raw, i) => {
    const line = i + 1;
    const trimmed = raw.trim();
    if (trimmed === '' || trimmed.startsWith('#')) return;
    const fields = trimmed.split(/\t+|\s+/);
    if (fields.length !== 5) {
      errors.push({ line, reason: `expected 5 fields, found ${fields.length}` });
      return;
    }
    const [sys, comp, name, valueText, typeText] = fields;
    const systemId = Number(sys);
    const componentId = Number(comp);
    const value = Number(valueText);
    const type = paramTypeName(Number(typeText));
    if (!Number.isInteger(systemId) || !Number.isInteger(componentId)) errors.push({ line, reason: 'bad vehicle or component id' });
    else if (!/^[\x21-\x7e]{1,16}$/.test(name)) errors.push({ line, reason: 'bad parameter name' });
    else if (!Number.isFinite(value)) errors.push({ line, reason: `bad value for ${name}` });
    else if (!type) errors.push({ line, reason: `unknown type ${typeText} for ${name}` });
    else rows.push({ line, systemId, componentId, name, value, type });
  });
  return { rows, errors };
}
