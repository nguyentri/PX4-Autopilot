/** One received line; `time` is when its first character arrived. */
interface ScrollbackLine { time: Date; text: string }

const pad = (value: number, width = 2): string => String(value).padStart(width, '0');

export function formatTimestamp(time: Date): string {
  return `${pad(time.getHours())}:${pad(time.getMinutes())}:${pad(time.getSeconds())}.${pad(time.getMilliseconds(), 3)}`;
}

/** `<setup>-<core>-<yymmdd-hhmmss>.log`; the setup name is reduced to a safe slug. */
export function logFileName(setup: string, core: string, time = new Date()): string {
  const slug = setup.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 50) || 'setup';
  const stamp = `${pad(time.getFullYear() % 100)}${pad(time.getMonth() + 1)}${pad(time.getDate())}-` +
    `${pad(time.getHours())}${pad(time.getMinutes())}${pad(time.getSeconds())}`;
  return `${slug}-${core}-${stamp}.log`;
}

/**
 * Line ring buffer of one core's RTT output. The last line may still be open
 * (an NSH prompt has no newline). Rendering adds timestamps at line starts, so
 * toggling them re-renders the same text.
 */
export class RttScrollback {
  private lines: ScrollbackLine[] = [];
  private open = false;

  constructor(private limit: number) {}

  public setLimit(limit: number): void { this.limit = Math.max(100, limit); this.trim(); }

  /** Appends received text and returns it rendered for the terminal. */
  public append(text: string, timestamps: boolean, time = new Date()): string {
    let rendered = '';
    for (const piece of text.split(/(\n)/)) {
      if (piece === '\n') {
        if (!this.open) { this.lines.push({ time, text: '' }); if (timestamps) { rendered += this.stamp(time); } }
        this.open = false;
        rendered += '\r\n';
        continue;
      }
      const clean = piece.replace(/\r/g, '');
      if (!clean) { continue; }
      if (this.open) { this.lines[this.lines.length - 1].text += clean; }
      else {
        this.lines.push({ time, text: clean });
        this.open = true;
        if (timestamps) { rendered += this.stamp(time); }
      }
      rendered += clean;
    }
    this.trim();
    return rendered;
  }

  /** The whole buffer rendered for a terminal (CRLF line ends). */
  public render(timestamps: boolean): string {
    const body = this.lines.map((line) => (timestamps ? this.stamp(line.time) : '') + line.text).join('\r\n');
    return this.lines.length && !this.open ? body + '\r\n' : body;
  }

  /** Plain text for the clipboard or a log file (LF line ends). */
  public text(timestamps: boolean): string {
    // PX4 logs colour their levels; a saved log keeps the words, not the escapes.
    const lines = this.lines.map((line) => (timestamps ? `${formatTimestamp(line.time)}  ` : '') +
      line.text.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, ''));
    return lines.length ? lines.join('\n') + '\n' : '';
  }

  public lineCount(): number { return this.lines.length; }

  public clear(): void { this.lines = []; this.open = false; }

  private stamp(time: Date): string { return `\x1b[2m${formatTimestamp(time)}\x1b[0m  `; }

  private trim(): void {
    if (this.lines.length > this.limit) { this.lines.splice(0, this.lines.length - this.limit); }
  }
}
