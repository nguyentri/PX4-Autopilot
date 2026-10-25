import * as path from 'path';
import * as vscode from 'vscode';
import { SelectionStore } from './selection-store';

export class Px4NuttxTaskProvider implements vscode.TaskProvider {
  static readonly TaskType = 'px4-nuttx';

  constructor(
    private readonly workspaceRoot: string,
    private readonly store: SelectionStore,
    private readonly workspaceFolder?: vscode.WorkspaceFolder
  ) {}

  public provideTasks(): vscode.ProviderResult<vscode.Task[]> {
    if (vscode.workspace?.isTrusted === false) {
      return [];
    }
    return [
      this.createTask('build', 'Build Active Firmware Target', ['build']),
      this.createTask('cleanRebuild', 'Clean Rebuild Active Firmware Target', ['build', '--clean']),
      this.createTask('doctor', 'Check Prerequisites (Doctor)', ['doctor']),
    ];
  }

  public resolveTask(task: vscode.Task): vscode.Task | undefined {
    if (vscode.workspace?.isTrusted === false) {
      return undefined;
    }
    const definition = task.definition as vscode.TaskDefinition;
    if (definition.type !== Px4NuttxTaskProvider.TaskType) {
      return undefined;
    }
    if (definition.operation === 'build') {
      return this.createTask('build', task.name || 'Build Active Firmware Target', ['build'], definition.selection);
    }
    if (definition.operation === 'cleanRebuild') {
      return this.createTask('cleanRebuild', task.name || 'Clean Rebuild Active Firmware Target', ['build', '--clean'], definition.selection);
    }
    if (definition.operation === 'doctor') {
      return this.createTask('doctor', task.name || 'Check Prerequisites (Doctor)', ['doctor'], definition.selection);
    }
    return undefined;
  }

  private getTaskScope(): vscode.WorkspaceFolder | vscode.TaskScope {
    if (this.workspaceFolder) {
      return this.workspaceFolder;
    }
    return vscode.workspace.workspaceFolders?.find((folder) => folder.uri.fsPath === this.workspaceRoot)
      || vscode.TaskScope.Workspace;
  }

  public createTask(
    operation: string,
    name: string,
    cliArgs: string[],
    selectionPath?: string
  ): vscode.Task {
    const config = vscode.Uri?.file
      ? vscode.workspace.getConfiguration('px4Nuttx', vscode.Uri.file(this.workspaceRoot))
      : vscode.workspace.getConfiguration('px4Nuttx');
    const python = config.get<string>('pythonPath', 'python3');
    const script = path.join(this.workspaceRoot, 'Tools', 'firmware-workspace.py');
    const selFile = selectionPath || this.store.writeSelectionSnapshot(this.store.getSelection());

    const args = [script, ...cliArgs, '--selection', selFile, '--json'];
    const execution = new vscode.ProcessExecution(python, args, {
      cwd: this.workspaceRoot,
      env: {
        PYTHONPATH: `${path.join(this.workspaceRoot, 'Tools')}:${process.env.PYTHONPATH || ''}`,
      },
    });

    const taskDefinition: vscode.TaskDefinition = {
      type: Px4NuttxTaskProvider.TaskType,
      operation,
      selection: selFile,
    };

    const task = new vscode.Task(
      taskDefinition,
      this.getTaskScope(),
      name,
      'PX4/NuttX',
      execution,
      ['$gcc']
    );
    if (operation === 'build' || operation === 'cleanRebuild') {
      task.group = vscode.TaskGroup.Build;
    }
    return task;
  }
}

