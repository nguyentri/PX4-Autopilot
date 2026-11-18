// Turns the raw bytes typed into the console into journal lines. A line is
// complete when its line end is sent. Backspace (0x7f or 0x08) edits the
// pending line; every other control byte is kept in a visible escaped form,
// for example `<ESC>[A` for the up arrow. No `vscode` import.

const NAMES: Record<number, string> = {
  0x00: 'NUL', 0x01: 'SOH', 0x02: 'STX', 0x03: 'ETX', 0x04: 'EOT', 0x05: 'ENQ', 0x06: 'ACK', 0x07: 'BEL',
  0x09: 'TAB', 0x0b: 'VT', 0x0c: 'FF', 0x0e: 'SO', 0x0f: 'SI', 0x10: 'DLE', 0x11: 'DC1', 0x12: 'DC2',
  0x13: 'DC3', 0x14: 'DC4', 0x15: 'NAK', 0x16: 'SYN', 0x17: 'ETB', 0x18: 'CAN', 0x19: 'EM', 0x1a: 'SUB',
  0x1b: 'ESC', 0x1c: 'FS', 0x1d: 'GS', 0x1e: 'RS', 0x1f: 'US',
};

/** Longest pending line kept; longer input is still sent but the journal line is cut. */
export const MAX_LINE = 4096;

export class ConsoleLineAssembler {
  /** One element per typed character, so backspace removes a whole `<ESC>` token. */
  private pending: string[] = [];
  private lastWasCr = false;

  /** Feed typed text; returns the lines completed by it. */
  feed(text: string): string[] {
    const lines: string[] = [];
    for (const ch of text) {
      const code = ch.codePointAt(0) ?? 0;
      if (ch === '\r' || ch === '\n') {
        // "\r\n" is one line end, not an empty second line.
        if (!(ch === '\n' && this.lastWasCr)) lines.push(this.take());
        this.lastWasCr = ch === '\r';
        continue;
      }
      this.lastWasCr = false;
      if (code === 0x7f || code === 0x08) {
        this.pending.pop();
      } else if (code < 0x20) {
        this.push(`<${NAMES[code] ?? `0x${code.toString(16).padStart(2, '0')}`}>`);
      } else {
        this.push(ch);
      }
    }
    return lines;
  }

  /** The line typed so far (for a journal flush when the console closes mid-line). */
  get partial(): string {
    return this.pending.join('');
  }

  reset(): void {
    this.pending = [];
    this.lastWasCr = false;
  }

  private push(token: string): void {
    if (this.pending.length < MAX_LINE) this.pending.push(token);
  }

  private take(): string {
    const line = this.pending.join('');
    this.pending = [];
    return line;
  }
}
