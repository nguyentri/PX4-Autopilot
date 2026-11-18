// Multi-line pastes into the vehicle shell wait for an explicit Send: each
// line runs as soon as its line end arrives.

/** Lines in a paste; one trailing line end does not count as an extra line. */
export function pasteLineCount(text: string): number {
  const trimmed = text.replace(/(\r\n|\r|\n)$/, '');
  return trimmed.split(/\r\n|\r|\n/).length;
}

/** The text sent after Send: every line end becomes CR, as typed at the prompt. */
export function pasteToShell(text: string): string {
  return text.replace(/\r\n|\n/g, '\r');
}
