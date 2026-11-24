// The one audit sink of a window session: an append-only list of
// {time, kind, data}. Console lines, guarded commands, parameter writes,
// recordings, log downloads, link changes, mode and arming changes and status
// text all land here; the session report reads it. No `vscode` import.

export const JOURNAL_CAPACITY = 20000;

export type JournalKind =
  | 'console_opened' | 'console_declined' | 'console_line'
  | 'command' | 'param_write' | 'param_import' | 'recording' | 'log_download' | 'connection'
  | 'link' | 'mode' | 'arming' | 'statustext';

export interface JournalEntry {
  /** ISO 8601 wall-clock time of the append. */
  time: string;
  kind: JournalKind;
  data: Record<string, unknown>;
}

type Listener = (entry: JournalEntry) => void;

export class SessionJournal {
  private readonly items: JournalEntry[] = [];
  private readonly listeners = new Set<Listener>();
  /** Oldest entries dropped because the journal reached its capacity. */
  dropped = 0;

  constructor(private readonly capacity = JOURNAL_CAPACITY, private readonly now: () => Date = () => new Date()) {}

  append(kind: JournalKind, data: Record<string, unknown> = {}): JournalEntry {
    const entry: JournalEntry = { time: this.now().toISOString(), kind, data };
    this.items.push(entry);
    if (this.items.length > this.capacity) {
      this.items.splice(0, this.items.length - this.capacity);
      this.dropped += 1;
    }
    for (const listener of [...this.listeners]) listener(entry);
    return entry;
  }

  entries(kind?: JournalKind): JournalEntry[] {
    return kind ? this.items.filter((e) => e.kind === kind) : [...this.items];
  }

  onDidAppend(listener: Listener): { dispose(): void } {
    this.listeners.add(listener);
    return { dispose: () => this.listeners.delete(listener) };
  }
}
