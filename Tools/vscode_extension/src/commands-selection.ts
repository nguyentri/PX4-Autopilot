import * as path from 'path';
import * as vscode from 'vscode';
import { BackendClient, WorkspaceTrustError } from './backend-client';
import { SelectionStore } from './selection-store';
import { CatalogData, FirmwareSelection, GroupMetadata } from './types';
import {
  ArtifactsViewProvider,
  OperationsViewProvider,
  ReadinessViewProvider,
  SelectionViewProvider,
} from './workspace-view';

function ensureTrusted(action: string): boolean {
  if (vscode.workspace?.isTrusted !== false) {
    return true;
  }
  vscode.window.showErrorMessage(`Workspace trust is required to ${action}.`);
  return false;
}

function boardCoreCapability(data: CatalogData, board: string, core: string): any {
  return data.devices?.[board]?.cores?.[core];
}

function withCapabilities(
  data: CatalogData,
  selection: FirmwareSelection,
  loadRecipe?: string,
  groupMembers?: Array<{ core: string; family: 'px4' | 'nuttx'; target?: string; config?: string }>
): FirmwareSelection {
  const members = groupMembers || [{ core: selection.core, family: selection.build.family as 'px4' | 'nuttx' }];
  const capabilities = members.map((member) => boardCoreCapability(data, selection.board, member.core));
  const build = capabilities.length > 0 && capabilities.every((capability) => capability?.buildAvailable);
  const load = capabilities.length > 0 && capabilities.every((capability) => capability?.loadAvailable);
  const debug = capabilities.length > 0 && capabilities.every((capability) => capability?.debugAvailable);
  const result = { ...selection };
  if (!build) {
    return result;
  }
  if (load && loadRecipe) {
    result.load = { recipe: loadRecipe };
  }
  if (debug) {
    result.debug = { mode: 'attach' };
  }
  return result;
}

export function registerSelectionCommands(
  context: vscode.ExtensionContext,
  client: BackendClient,
  store: SelectionStore,
  selectionView: SelectionViewProvider,
  readinessView: ReadinessViewProvider,
  artifactsView?: ArtifactsViewProvider,
  operationsView?: OperationsViewProvider
): void {
  context.subscriptions.push(
    vscode.commands.registerCommand('px4Nuttx.checkDoctor', async () => {
      if (!ensureTrusted('run prerequisite checks')) {
        return;
      }
      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: 'Checking Prerequisites (Doctor)...' },
        async (_progress, token) => {
          try {
            const res = await client.runDoctor(undefined, { cancellationToken: token });
            await readinessView.setDoctorData(res.data);
            if (res.status === 'ok') {
              const readiness = res.data?.readiness;
              const message = readiness
                ? `Build ${readiness.build ? 'ready' : 'blocked'}; load ${readiness.load ? 'ready' : 'blocked'}; debug ${readiness.debug ? 'ready' : 'blocked'}; console ${readiness.console ? 'ready' : 'blocked'}.`
                : (res.data?.probes?.length
                  ? 'Build prerequisites are available; inspect Readiness for target-tool status.'
                  : 'Build ready. Connect/select a probe to load or debug.');
              vscode.window.showInformationMessage(message);
            } else {
              const errs = res.diagnostics.filter((diagnostic) => diagnostic.level === 'error').map((diagnostic) => diagnostic.message);
              const choice = await vscode.window.showErrorMessage(
                `Prerequisite issues found: ${errs.join('; ') || 'See Readiness for details.'}`,
                'View Local Guide'
              );
              if (choice === 'View Local Guide') {
                const guide = path.join(store.getWorkspaceRoot(), 'docs', 'vscode-extension.md');
                await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(guide));
              }
            }
          } catch (error) {
            const message = error instanceof WorkspaceTrustError ? error.message : (error as Error).message;
            vscode.window.showErrorMessage(`Doctor check failed: ${message}`);
          }
        }
      );
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('px4Nuttx.selectProfile', async () => {
      if (!ensureTrusted('load the firmware catalog')) {
        return;
      }
      try {
        const catRes = await client.getCatalog();
        if (catRes.status !== 'ok') {
          throw new Error(catRes.diagnostics.map((diagnostic) => diagnostic.message).join('; ') || 'Catalog lookup failed.');
        }
        const data = catRes.data;
        store.setCatalog(data);

        interface ProfileQuickPickItem extends vscode.QuickPickItem {
          selection?: FirmwareSelection;
        }

        const items: ProfileQuickPickItem[] = [];
        items.push({ label: 'PX4 Autopilot Targets', kind: vscode.QuickPickItemKind.Separator });
        for (const target of data.px4Targets) {
          const selection = withCapabilities(data, {
            schemaVersion: 1,
            id: target.target.replace(/^renesas_/, ''),
            board: target.board as FirmwareSelection['board'],
            core: target.core as FirmwareSelection['core'],
            build: { family: 'px4', target: target.target, mode: 'incremental' },
          }, 'rzv-cr8-ram');
          items.push({
            label: `$(circuit-board) ${target.target}`,
            description: `${target.board}:${target.core}`,
            detail: `PX4 autopilot target (${target.file})${selection.debug ? '' : ' · build only'}`,
            selection,
          });
        }

        items.push({ label: 'Standalone NuttX Configurations', kind: vscode.QuickPickItemKind.Separator });
        for (const [board, configs] of Object.entries(data.nuttxConfigs)) {
          for (const config of configs) {
            const selection = withCapabilities(data, {
              schemaVersion: 1,
              id: `${board}-${config.config}`,
              board: config.board as FirmwareSelection['board'],
              core: config.core as FirmwareSelection['core'],
              build: { family: 'nuttx', config: config.config, mode: 'incremental' },
            }, 'rzv-cr8-ram');
            items.push({
              label: `$(file-binary) ${board}:${config.config}`,
              description: `${config.board}:${config.core}`,
              detail: `Standalone NuttX configuration${selection.debug ? '' : ' · build only'}`,
              selection,
            });
          }
        }

        items.push({ label: 'Multicore Pair Groups', kind: vscode.QuickPickItemKind.Separator });
        for (const [groupId, rawGroup] of Object.entries(data.groups)) {
          const group = rawGroup as GroupMetadata;
          const members = (group.members || []) as Array<{ core: string; family: 'px4' | 'nuttx'; target?: string; config?: string }>;
          const family = group.family || members[0]?.family || 'nuttx';
          const selection = withCapabilities(data, {
            schemaVersion: 1,
            id: groupId,
            board: group.board as FirmwareSelection['board'],
            core: 'multicore',
            group: groupId,
            build: { family, mode: 'incremental' },
          }, group.loadRecipe, members);
          items.push({
            label: `$(layers) ${group.name}`,
            description: `${group.board} (Multicore)`,
            detail: `${group.description || ''}${selection.load ? '' : ' · build only'}`,
            selection,
          });
        }

        const picked = await vscode.window.showQuickPick(items, {
          placeHolder: 'Select a PX4 target, NuttX config, or Multicore Group profile',
          matchOnDescription: true,
          matchOnDetail: true,
        });
        if (picked?.selection) {
          await store.setSelection(picked.selection);
          selectionView.refresh();
          operationsView?.refresh();
          artifactsView?.refresh();
        }
      } catch (error) {
        vscode.window.showErrorMessage(`Failed loading target catalog: ${(error as Error).message}`);
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('px4Nuttx.selectCore', async () => {
      if (!ensureTrusted('select a group core')) {
        return;
      }
      const members = store.getGroupMembers();
      if (members.length === 0) {
        vscode.window.showInformationMessage('The selected profile has one fixed core.');
        return;
      }
      const picked = await vscode.window.showQuickPick(
        members.map((member) => ({
          label: `$(cpu) ${member.core}`,
          description: `${member.family.toUpperCase()} · ${store.getConsoleTransport(member.core).toUpperCase()}`,
          core: member.core,
        })),
        { placeHolder: 'Select the group core for load, debug or console' }
      );
      if (picked) {
        await store.setSelectedCore(picked.core);
        selectionView.refresh();
        operationsView?.refresh();
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('px4Nuttx.selectProbe', async () => {
      if (!ensureTrusted('enumerate debug probes')) {
        return;
      }
      try {
        const docRes = await client.runDoctor();
        const probes = docRes.data?.probes || [];
        const items = probes.map((probe) => ({
          label: `$(plug) J-Link: ${probe.product}`,
          description: `Serial: ${probe.serial}`,
          serial: probe.serial,
        }));
        items.push({ label: '$(edit) Enter Serial Manually...', description: 'Type probe serial number', serial: 'manual' });
        const picked = await vscode.window.showQuickPick(items, { placeHolder: 'Select target J-Link debug probe' });
        if (!picked) {
          return;
        }
        const serial = picked.serial === 'manual'
          ? await vscode.window.showInputBox({ prompt: 'Enter SEGGER J-Link serial number', placeHolder: 'e.g. 1061999999' })
          : picked.serial;
        if (serial?.trim()) {
          await store.setSelectedProbe(serial);
          selectionView.refresh();
        }
      } catch (error) {
        vscode.window.showErrorMessage(`Failed enumerating probes: ${(error as Error).message}`);
      }
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand('px4Nuttx.refresh', async () => {
      selectionView.refresh();
      readinessView.refresh();
      artifactsView?.refresh();
      operationsView?.refresh();
      if (!ensureTrusted('refresh the firmware catalog')) {
        return;
      }
      try {
        const [catalog, doctor] = await Promise.all([client.getCatalog(), client.runDoctor()]);
        if (catalog.status === 'ok') {
          store.setCatalog(catalog.data);
          selectionView.refresh();
          artifactsView?.refresh();
          operationsView?.refresh();
        }
        if (doctor.data) {
          await readinessView.setDoctorData(doctor.data);
        }
      } catch {
        // The views retain their last known state when a refresh is unavailable.
      }
    })
  );
}

