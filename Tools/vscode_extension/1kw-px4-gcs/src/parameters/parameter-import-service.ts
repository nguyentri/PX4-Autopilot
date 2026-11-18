// QGC `.params` export and import. Import: refused while armed; rows for
// another vehicle are ignored; unknown, internal, volatile and wrong-type rows
// are listed and never written; a read-only preview and a counts modal come
// first; a snapshot of the current values is saved before the first write;
// values are applied one at a time with read-back and the run stops on link
// loss or when the vehicle arms. No `vscode` import: the UI is injected.
import { linkRefusal } from '../control/command-preconditions';
import { Confirmation } from '../control/confirmation-text';
import { captureSnapshot, VehicleContext } from '../control/guarded-command-service';
import { ParamEntry } from '../dashboard/dashboard-messages';
import { SessionJournal } from '../session/session-journal';
import { ParameterEditService } from './parameter-edit-service';
import { safetyClass } from './parameter-edit-policy';
import { ParameterStore } from './parameter-store';
import { formatParamFileValue, formatParamsFile, parseParamsFile, ParsedParamsFile, sameParamValue } from './qgc-params-file';

export interface ImportChange {
  name: string;
  type: string;
  current: number | null;
  next: number;
  /** Safety class name when the parameter belongs to a safety-relevant family. */
  safety?: string;
}

export interface ImportPlan {
  changes: ImportChange[];
  unchanged: number;
  /** Rows for another vehicle or component id. */
  ignored: number;
  /** Rows never written, with the reason (unknown, internal, volatile, type). */
  skipped: { name: string; reason: string }[];
  errors: { line: number; reason: string }[];
}

export interface ImportSummary {
  result: 'refused' | 'declined' | 'nothing to change' | 'completed' | 'stopped';
  message: string;
  applied: string[];
  notApplied: { name: string; value: number | null }[];
  notAttempted: string[];
  snapshot?: string;
}

export function planImport(parsed: ParsedParamsFile, entry: (name: string) => ParamEntry | undefined,
  systemId: number, componentId: number): ImportPlan {
  const plan: ImportPlan = { changes: [], unchanged: 0, ignored: 0, skipped: [], errors: [...parsed.errors] };
  for (const row of parsed.rows) {
    if (row.systemId !== systemId || row.componentId !== componentId) {
      plan.ignored += 1;
      continue;
    }
    const current = entry(row.name);
    if (row.name.startsWith('_')) plan.skipped.push({ name: row.name, reason: 'internal parameter' });
    else if (!current) plan.skipped.push({ name: row.name, reason: 'unknown on this vehicle' });
    else if (current.meta?.volatile) plan.skipped.push({ name: row.name, reason: 'volatile' });
    else if (current.type !== row.type) {
      plan.skipped.push({ name: row.name, reason: `file type ${row.type}, vehicle type ${current.type}` });
    } else if (current.value !== null && sameParamValue(current.value, row.value, row.type)) plan.unchanged += 1;
    else {
      plan.changes.push({ name: row.name, type: row.type, current: current.value, next: row.value,
        ...(safetyClass(row.name) ? { safety: safetyClass(row.name)?.cls } : {}) });
    }
  }
  return plan;
}

function valueText(value: number | null, type: string): string {
  return value === null ? 'unknown' : formatParamFileValue(value, type);
}

/** Plain-text preview: every change, then the ignored, skipped and malformed rows. */
export function previewText(plan: ImportPlan, origin: string): string {
  const lines = [`Parameter import preview: ${origin}`, '', `Changes (${plan.changes.length}): name, current value -> new value`];
  for (const c of plan.changes) {
    lines.push(`  ${c.name}\t${valueText(c.current, c.type)} -> ${valueText(c.next, c.type)}${c.safety ? `\t[${c.safety}]` : ''}`);
  }
  lines.push('', `Unchanged: ${plan.unchanged}`, `Ignored (another vehicle or component): ${plan.ignored}`, '',
    `Not written (${plan.skipped.length}):`);
  for (const s of plan.skipped) lines.push(`  ${s.name}\t${s.reason}`);
  if (plan.errors.length > 0) {
    lines.push('', `Unreadable lines (${plan.errors.length}):`);
    for (const e of plan.errors) lines.push(`  line ${e.line}: ${e.reason}`);
  }
  return `${lines.join('\n')}\n`;
}

export function importConfirmation(plan: ImportPlan, origin: string): Confirmation {
  const safety = plan.changes.filter((c) => c.safety).length;
  return {
    message: `Write ${plan.changes.length} parameter changes from ${origin}?`,
    detail: [
      `Changes: ${plan.changes.length} (safety-relevant: ${safety})`,
      `Unchanged: ${plan.unchanged}`,
      `Ignored (another vehicle or component): ${plan.ignored}`,
      `Unknown or never written: ${plan.skipped.length}`,
      'The preview document lists every change. The current values are saved as a snapshot before the first write.',
    ].join('\n'),
    button: 'Write parameters',
  };
}

export interface ImportOptions extends VehicleContext {
  params: ParameterStore;
  editor: ParameterEditService;
  journal: SessionJournal;
  confirm(confirmation: Confirmation): Promise<boolean>;
  showPreview(text: string): Promise<void>;
  /** Save the snapshot `.params` text; returns where it went. */
  saveSnapshot(text: string): Promise<string>;
  /** Show the summary; true when the operator chose "Restore snapshot". */
  offerRestore(summary: ImportSummary): Promise<boolean>;
  readFile(file: string): Promise<string>;
}

export class ParameterImportService {
  constructor(private readonly options: ImportOptions) {}

  /** The vehicle's current values as a QGC file (internal and volatile parameters left out). */
  exportText(): string {
    const link = this.options.controller.link;
    const rows = this.options.params.entries()
      .filter((p) => p.value !== null && !p.meta?.volatile && !p.name.startsWith('_'))
      .map((p) => ({ name: p.name, value: p.value as number, type: p.type }));
    const meta = this.options.params.metadata;
    return formatParamsFile(rows, link?.systemId ?? 1, link?.componentId ?? 1,
      [`Exported by 1KW-Px4-GCS`, `Metadata: ${meta ? meta.target : 'none'}`]);
  }

  async importFile(file: string, allowRestore = true): Promise<ImportSummary> {
    return this.importText(await this.options.readFile(file), file, allowRestore);
  }

  async importText(text: string, origin: string, allowRestore = true): Promise<ImportSummary> {
    const { options } = this;
    const refusal = this.refusal();
    if (refusal) return this.finish(origin, { result: 'refused', message: refusal });
    await options.params.load(false);
    if (options.params.state.state !== 'done') {
      return this.finish(origin, { result: 'refused', message: 'The parameter list could not be read.' });
    }
    const link = options.controller.link;
    const plan = planImport(parseParamsFile(text), (n) => options.params.entry(n), link?.systemId ?? 1,
      link?.componentId ?? 1);
    if (plan.changes.length === 0) {
      return this.finish(origin, { result: 'nothing to change',
        message: `Nothing to write: ${plan.unchanged} unchanged, ${plan.ignored} ignored, ${plan.skipped.length} not written.` },
      plan);
    }
    await options.showPreview(previewText(plan, origin));
    if (!(await options.confirm(importConfirmation(plan, origin)))) {
      return this.finish(origin, { result: 'declined', message: 'Cancelled; nothing was written.' }, plan);
    }
    const late = this.refusal();
    if (late) return this.finish(origin, { result: 'refused', message: `Not written: ${late}` }, plan);
    const snapshot = await options.saveSnapshot(this.exportText());
    const applied: string[] = [];
    const notApplied: { name: string; value: number | null }[] = [];
    let stop: string | undefined;
    let index = 0;
    for (; index < plan.changes.length; index += 1) {
      stop = this.refusal();
      if (stop) break;
      const change = plan.changes[index];
      const outcome = await options.editor.write(change.name, change.current, change.next, ['import']);
      if (outcome.result === 'applied') applied.push(change.name);
      else notApplied.push({ name: change.name, value: outcome.value });
    }
    const notAttempted = plan.changes.slice(index).map((c) => c.name);
    const summary: ImportSummary = {
      result: stop ? 'stopped' : 'completed',
      message: `${applied.length} applied, ${notApplied.length} not applied, ${notAttempted.length} not attempted`
        + `${stop ? ` (stopped: ${stop})` : ''}.`,
      applied, notApplied, notAttempted, snapshot,
    };
    this.finish(origin, summary, plan);
    if (allowRestore && applied.length > 0 && await options.offerRestore(summary)) {
      await this.importFile(snapshot, false);
    }
    return summary;
  }

  /** Why an import may not write now: the shared link guard, or an armed (or unknown) state. */
  private refusal(): string | undefined {
    const state = captureSnapshot(this.options);
    const link = linkRefusal(state);
    if (link) return link;
    if (state.armed !== false) return 'Parameter import is refused while the vehicle is armed.';
    return undefined;
  }

  private finish(origin: string, partial: Partial<ImportSummary> & Pick<ImportSummary, 'result' | 'message'>,
    plan?: ImportPlan): ImportSummary {
    const summary: ImportSummary = { applied: [], notApplied: [], notAttempted: [], ...partial };
    this.options.journal.append('param_import', {
      origin, result: summary.result, message: summary.message, applied: summary.applied,
      notApplied: summary.notApplied, notAttempted: summary.notAttempted, snapshot: summary.snapshot,
      ...(plan ? { changes: plan.changes.length, unchanged: plan.unchanged, ignored: plan.ignored,
        skipped: plan.skipped } : {}),
    });
    return summary;
  }
}
