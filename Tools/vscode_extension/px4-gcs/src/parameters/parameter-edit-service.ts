// One parameter write from the edit popover: parse for the vehicle's type,
// apply the confirmation policy, write once through the sidecar (which
// verifies by echo or read-back), update the list and journal old value,
// new value and result. No `vscode` import: the modal is injected.
import { linkRefusal } from '../control/command-preconditions';
import { Confirmation } from '../control/confirmation-text';
import { captureSnapshot, VehicleContext } from '../control/guarded-command-service';
import { ParamOutcomeView } from '../dashboard/dashboard-messages';
import { SessionJournal } from '../session/session-journal';
import { editReasons, nameRefusal, parseParamValue } from './parameter-edit-policy';
import { ParameterStore } from './parameter-store';
import { formatParamFileValue } from './qgc-params-file';

/** The sidecar waits for the echo, then reads back once; this bounds a stuck sidecar. */
const WRITE_TIMEOUT_MS = 10000;

export interface ParamWriteReply {
  name: string;
  applied: boolean;
  value: number | null;
  requested: number;
  type: string;
  echoed: boolean;
}

export interface ParameterEditOptions extends VehicleContext {
  params: ParameterStore;
  journal: SessionJournal;
  confirm(confirmation: Confirmation): Promise<boolean>;
}

export function paramEditConfirmation(name: string, oldText: string, newText: string, reasons: string[]): Confirmation {
  return {
    message: `Write ${name} = ${newText}?`,
    detail: [`Current value: ${oldText}.`, 'This edit needs confirmation because:', ...reasons.map((r) => `• ${r}`)]
      .join('\n'),
    button: 'Write parameter',
  };
}

export class ParameterEditService {
  constructor(private readonly options: ParameterEditOptions) {}

  async edit(name: string, text: string): Promise<ParamOutcomeView> {
    const { params } = this.options;
    const entry = params.entry(name);
    const old = entry?.value ?? null;
    const hidden = nameRefusal(name);
    if (hidden) return this.finish(name, old, null, 'refused', hidden);
    if (!entry) return this.finish(name, old, null, 'refused', `${name} is not in the vehicle's parameter list.`);
    const parsed = parseParamValue(text, entry.type);
    if ('error' in parsed) return this.finish(name, old, null, 'refused', parsed.error);
    const value = parsed.value;
    const reasons = (): string[] => editReasons({
      name, type: entry.type, value, armed: captureSnapshot(this.options).armed,
      metadataLoaded: params.metadata !== undefined, meta: params.meta(name),
    });
    const first = this.refusal();
    if (first) return this.finish(name, old, value, 'refused', first);
    const confirmed = reasons();
    if (confirmed.length > 0) {
      const oldText = old === null ? 'unknown' : formatParamFileValue(old, entry.type);
      const ok = await this.options.confirm(
        paramEditConfirmation(name, oldText, formatParamFileValue(value, entry.type), confirmed));
      if (!ok) return this.finish(name, old, value, 'declined', 'Cancelled; nothing was written.', confirmed);
      const late = this.refusal();
      if (late) return this.finish(name, old, value, 'refused', `Not written: ${late}`, confirmed);
      const added = reasons().filter((r) => !confirmed.includes(r));
      if (added.length > 0) {
        return this.finish(name, old, value, 'refused', `Not written: the state changed (${added.join('; ')}).`, confirmed);
      }
    }
    return this.write(name, old, value, confirmed);
  }

  /** Write without a dialog (the import confirmed the whole set). */
  async write(name: string, old: number | null, value: number, reasons: string[] = []): Promise<ParamOutcomeView> {
    const client = this.options.controller.client;
    if (!client) return this.finish(name, old, value, 'refused', 'Not written: the link closed.', reasons);
    try {
      const reply = await client.request<ParamWriteReply>('param_set', { name, value }, { timeoutMs: WRITE_TIMEOUT_MS });
      this.options.params.applyValue(name, reply.value);
      const result = reply.applied ? 'applied' : 'not applied';
      const message = reply.applied ? `${name} = ${reply.value}: applied.`
        : `${name}: not applied; the vehicle holds ${reply.value}.`;
      return this.finish(name, old, value, result, message, reasons, reply.value);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return this.finish(name, old, value, 'failed', `${name}: failed: ${message}`, reasons);
    }
  }

  private refusal(): string | undefined {
    return linkRefusal(captureSnapshot(this.options));
  }

  private finish(name: string, old: number | null, requested: number | null, result: string, message: string,
    reasons: string[] = [], held: number | null = old): ParamOutcomeView {
    this.options.journal.append('param_write', { name, old, requested, result, value: held, reasons, message });
    return { name, result, value: held, message };
  }
}
