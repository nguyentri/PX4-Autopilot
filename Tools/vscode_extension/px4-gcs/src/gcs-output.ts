import * as vscode from 'vscode';

/** The "Px4-GCS" output channel: timestamped lines, plus once-per-connection notes. */
export class GcsOutput implements vscode.Disposable {
  private readonly channel = vscode.window.createOutputChannel('Px4-GCS');
  private readonly onceKeys = new Set<string>();

  log(line: string): void {
    this.channel.appendLine(`[${new Date().toISOString().slice(11, 23)}] ${line}`);
  }

  /** Log `line` only the first time `key` is seen since the last `resetOnce`. */
  once(key: string, line: string): void {
    if (this.onceKeys.has(key)) return;
    this.onceKeys.add(key);
    this.log(line);
  }

  resetOnce(): void {
    this.onceKeys.clear();
  }

  show(): void {
    this.channel.show(true);
  }

  dispose(): void {
    this.channel.dispose();
  }
}
