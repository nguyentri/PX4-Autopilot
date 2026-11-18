// Host-side STATUSTEXT history: the vehicle store keeps only the latest text,
// but a reopened dashboard must show the log again. Oldest entries go first.
import { STATUS_LOG_CAPACITY, StatusEntry } from './dashboard-messages';

export class StatusLogBuffer {
  private readonly items: StatusEntry[] = [];

  constructor(private readonly capacity = STATUS_LOG_CAPACITY) {}

  /** Store one `statustext` event payload; returns the entry the page receives. */
  add(ts: number, data: { severity?: unknown; text?: unknown }): StatusEntry {
    const severity = typeof data.severity === 'number' ? data.severity : 6;
    const entry = { ts, severity, text: String(data.text ?? '') };
    this.items.push(entry);
    if (this.items.length > this.capacity) this.items.splice(0, this.items.length - this.capacity);
    return entry;
  }

  entries(): StatusEntry[] {
    return [...this.items];
  }

  clear(): void {
    this.items.length = 0;
  }
}
