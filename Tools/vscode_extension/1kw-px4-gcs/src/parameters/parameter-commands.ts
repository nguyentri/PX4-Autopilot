// Palette commands and VS Code plumbing for parameters: metadata discovery
// (QuickPick, per-workspace memory), refresh, `.params` export and import with
// a read-only preview document and a snapshot in the extension's storage.
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { confirmModal } from '../control/control-commands';
import { VehicleContext } from '../control/guarded-command-service';
import { readGcsSettings } from '../gcs-settings';
import { SessionJournal } from '../session/session-journal';
import { ParameterEditService } from './parameter-edit-service';
import { ImportSummary, ParameterImportService } from './parameter-import-service';
import { ParameterMetadataLoader } from './parameter-metadata-loader';
import { ParameterStore } from './parameter-store';

const PREVIEW_SCHEME = 'px4gcs-preview';

/** Serves preview text as read-only documents. */
class PreviewProvider implements vscode.TextDocumentContentProvider {
  private readonly texts = new Map<string, string>();
  private readonly changed = new vscode.EventEmitter<vscode.Uri>();
  readonly onDidChange = this.changed.event;
  private counter = 0;

  provideTextDocumentContent(uri: vscode.Uri): string {
    return this.texts.get(uri.path) ?? '';
  }

  async show(text: string): Promise<void> {
    this.counter += 1;
    const uri = vscode.Uri.from({ scheme: PREVIEW_SCHEME, path: `/parameter-import-${this.counter}.txt` });
    this.texts.set(uri.path, text);
    const doc = await vscode.workspace.openTextDocument(uri);
    await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Beside, preview: true, preserveFocus: true });
  }

  dispose(): void {
    this.changed.dispose();
  }
}

function stamp(): string {
  return new Date().toISOString().replace(/[:.]/g, '-');
}

export interface ParameterCommandsOptions extends VehicleContext {
  context: vscode.ExtensionContext;
  params: ParameterStore;
  editor: ParameterEditService;
  journal: SessionJournal;
  log(line: string): void;
}

export function registerParameterCommands(options: ParameterCommandsOptions): vscode.Disposable[] {
  const { context, params, controller } = options;
  const preview = new PreviewProvider();
  const loader = new ParameterMetadataLoader({
    settingPath: () => readGcsSettings().metadataPath,
    workspaceFolders: () => (vscode.workspace.workspaceFolders ?? []).map((f) => f.uri.fsPath),
    pick: async (files) => (await vscode.window.showQuickPick(
      files.map((file) => ({ label: path.basename(path.dirname(file)), description: file, file })),
      { placeHolder: 'Parameter metadata: which build matches the vehicle?' }))?.file,
    memory: context.workspaceState,
    log: options.log,
  });
  let metadataResolved = false;
  const resolveMetadata = async (choose: boolean): Promise<void> => {
    metadataResolved = true;
    params.setMetadata(await loader.resolve(choose));
  };
  const importer = new ParameterImportService({
    ...options,
    confirm: confirmModal,
    showPreview: (text) => preview.show(text),
    saveSnapshot: async (text) => {
      const dir = vscode.Uri.joinPath(context.globalStorageUri, 'parameter-snapshots').fsPath;
      await fs.promises.mkdir(dir, { recursive: true });
      const file = path.join(dir, `snapshot-${stamp()}.params`);
      await fs.promises.writeFile(file, text, 'utf8');
      return file;
    },
    offerRestore: async (summary: ImportSummary) => {
      const show = summary.notApplied.length > 0 || summary.result === 'stopped'
        ? vscode.window.showWarningMessage : vscode.window.showInformationMessage;
      return (await show(`Parameter import: ${summary.message}`, 'Restore snapshot')) === 'Restore snapshot';
    },
    readFile: (file) => fs.promises.readFile(file, 'utf8'),
  });
  const report = (summary: ImportSummary): void => {
    if (summary.result === 'refused' || summary.result === 'nothing to change') {
      void vscode.window.showWarningMessage(`Parameter import: ${summary.message}`);
    }
  };
  return [
    preview,
    vscode.workspace.registerTextDocumentContentProvider(PREVIEW_SCHEME, preview),
    controller.onDidChangeState((state) => {
      if (state === 'connected' && !metadataResolved) void resolveMetadata(false);
    }),
    vscode.commands.registerCommand('px4Gcs.refreshParameters', async () => {
      await resolveMetadata(true);
      if (controller.client) await params.load(true);
    }),
    vscode.commands.registerCommand('px4Gcs.exportParameters', async () => {
      if (!controller.client) {
        void vscode.window.showWarningMessage('Connect to a vehicle to export its parameters.');
        return;
      }
      await params.load(false);
      if (params.state.state !== 'done') {
        void vscode.window.showWarningMessage('The parameter list could not be read.');
        return;
      }
      const target = params.metadata?.target ?? `vehicle-${controller.link?.systemId ?? 1}`;
      const uri = await vscode.window.showSaveDialog({ filters: { 'QGC parameters': ['params'] },
        defaultUri: vscode.Uri.file(path.join(vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '', `${target}.params`)) });
      if (!uri) return;
      await fs.promises.writeFile(uri.fsPath, importer.exportText(), 'utf8');
      void vscode.window.showInformationMessage(`Parameters exported to ${uri.fsPath}.`);
    }),
    vscode.commands.registerCommand('px4Gcs.importParameters', async () => {
      const picked = await vscode.window.showOpenDialog({ canSelectMany: false,
        filters: { 'QGC parameters': ['params', 'txt'] } });
      if (picked?.[0]) report(await importer.importFile(picked[0].fsPath));
    }),
  ];
}
