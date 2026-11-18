// Palette commands for the guarded actions. They run through the same
// GuardedCommandService as the Fly tab buttons and show the outcome by name.
import * as vscode from 'vscode';
import { modeUnavailableReason } from './command-preconditions';
import { Confirmation } from './confirmation-text';
import { CommandOutcome, GuardedCommandService } from './guarded-command-service';

/** The editor-blocking warning used by every guarded action; VS Code adds Cancel as the default. */
export async function confirmModal(confirmation: Confirmation): Promise<boolean> {
  const choice = await vscode.window.showWarningMessage(confirmation.message,
    { modal: true, detail: confirmation.detail }, confirmation.button);
  return choice === confirmation.button;
}

export function showOutcome(outcome: CommandOutcome): void {
  if (outcome.result === 'declined') return;
  if (outcome.result === 'accepted') void vscode.window.showInformationMessage(outcome.message);
  else void vscode.window.showWarningMessage(outcome.message);
}

async function pickMode(service: GuardedCommandService): Promise<string | undefined> {
  const state = service.snapshot();
  const items = service.modes().map((mode) => {
    const unavailable = modeUnavailableReason(mode.key, state.availableModes);
    return {
      label: mode.name,
      key: mode.key,
      description: mode.key === state.modeKey ? 'current' : unavailable ?? (mode.needsSticks ? 'needs stick input' : ''),
    };
  });
  if (items.length === 0) {
    void vscode.window.showWarningMessage('No mode table: connect to a vehicle first.');
    return undefined;
  }
  return (await vscode.window.showQuickPick(items, { placeHolder: 'Flight mode to request' }))?.key;
}

export function registerControlCommands(service: GuardedCommandService): vscode.Disposable[] {
  const run = async (action: 'arm' | 'disarm' | 'reboot' | 'set_mode', mode?: string): Promise<void> => {
    showOutcome(await service.run(action, mode));
  };
  return [
    vscode.commands.registerCommand('px4Gcs.arm', () => run('arm')),
    vscode.commands.registerCommand('px4Gcs.disarm', () => run('disarm')),
    vscode.commands.registerCommand('px4Gcs.reboot', () => run('reboot')),
    vscode.commands.registerCommand('px4Gcs.setMode', async () => {
      const mode = await pickMode(service);
      if (mode) await run('set_mode', mode);
    }),
  ];
}
