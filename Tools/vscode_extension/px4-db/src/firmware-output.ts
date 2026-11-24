import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

export interface GccDiagnostic {
  file: string;
  line: number;
  column: number;
  severity: 'error' | 'warning';
  message: string;
}

const GCC_LINE = /^(.+?):(\d+):(?:(\d+):)?\s+(fatal error|error|warning):\s+(.*)$/;

/**
 * Parse one line of gcc/ld output. Only files inside the workspace are kept,
 * so toolchain and system headers never reach the Problems panel. A relative
 * path is tried against each base directory (make and ninja print paths
 * relative to their own working directory).
 */
export function parseGccLine(line: string, workspaceRoot: string, bases: string[] = [workspaceRoot],
  exists: (file: string) => boolean = fs.existsSync): GccDiagnostic | undefined {
  const match = GCC_LINE.exec(line.trim());
  if (!match) { return undefined; }
  const [, rawFile, rawLine, rawColumn, kind, message] = match;
  const candidates = path.isAbsolute(rawFile) ? [rawFile] : bases.map((base) => path.resolve(base, rawFile));
  const root = path.resolve(workspaceRoot) + path.sep;
  const file = candidates.find((candidate) => candidate.startsWith(root) && exists(candidate));
  if (!file) { return undefined; }
  return {
    file,
    line: Math.max(1, Number(rawLine)),
    column: Math.max(1, Number(rawColumn || 1)),
    severity: kind === 'warning' ? 'warning' : 'error',
    message: message.trim(),
  };
}

/**
 * The "Px4-DB Firmware" Output channel keeps every build's full log; gcc
 * diagnostics from it fill the Problems panel for workspace files.
 */
export class FirmwareOutput implements vscode.Disposable {
  private readonly channel: vscode.OutputChannel;
  private readonly problems: vscode.DiagnosticCollection;
  private readonly found = new Map<string, vscode.Diagnostic[]>();
  private readonly seen = new Set<string>();
  private partial = '';
  private readonly bases: string[];

  constructor(private readonly workspaceRoot: string) {
    this.channel = vscode.window.createOutputChannel('Px4-DB Firmware');
    this.problems = vscode.languages.createDiagnosticCollection('px4-db-firmware');
    this.bases = [workspaceRoot, path.join(workspaceRoot, 'platforms/nuttx/NuttX/nuttx')];
  }

  /** Starts a build section; Problems from the previous build are cleared. */
  public beginBuild(label: string): void {
    this.flush();
    this.found.clear();
    this.seen.clear();
    this.problems.clear();
    this.channel.appendLine(`=== ${label} · ${new Date().toLocaleString()} ===`);
  }

  public appendBuild(chunk: string, prefix = ''): void {
    const text = this.partial + chunk;
    const lines = text.split(/\r?\n/);
    this.partial = lines.pop() || '';
    for (const line of lines) { this.line(line, prefix); }
  }

  /** Ends a build section; a failure reveals the channel. */
  public finishBuild(ok: boolean, label: string): void {
    this.flush();
    this.channel.appendLine(`=== ${label}: ${ok ? 'succeeded' : 'failed'} ===`);
    if (!ok) { this.channel.show(true); }
  }

  public problemCount(): number {
    let count = 0;
    for (const list of this.found.values()) { count += list.length; }
    return count;
  }

  public show(): void { this.channel.show(true); }

  private flush(): void {
    if (this.partial) { this.line(this.partial, ''); this.partial = ''; }
  }

  private line(line: string, prefix: string): void {
    this.channel.appendLine(prefix ? `${prefix} ${line}` : line);
    const parsed = parseGccLine(line, this.workspaceRoot, this.bases);
    if (!parsed) { return; }
    const key = `${parsed.file}:${parsed.line}:${parsed.column}:${parsed.message}`;
    if (this.seen.has(key)) { return; }
    this.seen.add(key);
    const position = new vscode.Position(parsed.line - 1, parsed.column - 1);
    const diagnostic = new vscode.Diagnostic(new vscode.Range(position, position), parsed.message,
      parsed.severity === 'warning' ? vscode.DiagnosticSeverity.Warning : vscode.DiagnosticSeverity.Error);
    diagnostic.source = 'gcc';
    const list = this.found.get(parsed.file) || [];
    list.push(diagnostic);
    this.found.set(parsed.file, list);
    this.problems.set(vscode.Uri.file(parsed.file), list);
  }

  public dispose(): void {
    this.channel.dispose();
    this.problems.dispose();
  }
}
