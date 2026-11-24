// One status bar item: the link state, and mode/armed/battery while connected.
import * as vscode from 'vscode';
import { ConnectionController } from '../connection/connection-controller';
import { VehicleStateStore } from '../vehicle/vehicle-state-store';

export function statusBarText(controller: ConnectionController, store: VehicleStateStore): string {
  switch (controller.state) {
    case 'idle': return '$(debug-disconnect) PX4: offline';
    case 'connecting': return '$(sync~spin) PX4: connecting';
    case 'disconnecting': return '$(sync~spin) PX4: disconnecting';
    case 'lost': return '$(warning) PX4: link lost';
    default: break;
  }
  const hb = store.heartbeat;
  const voltage = store.get<{ voltage?: number }>('battery')?.voltage;
  const parts = [hb?.mode, hb ? (hb.armed ? 'ARMED' : 'disarmed') : undefined,
    typeof voltage === 'number' ? `${voltage.toFixed(1)} V` : undefined].filter(Boolean);
  return `$(plug) PX4${parts.length > 0 ? `: ${parts.join(' · ')}` : ''}`;
}

export class GcsStatusBar implements vscode.Disposable {
  private readonly item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  private readonly subscriptions: { dispose(): void }[];

  constructor(private readonly controller: ConnectionController, private readonly store: VehicleStateStore) {
    this.subscriptions = [controller.onDidChangeState(() => this.update()), store.onDidChange(() => this.update())];
    this.update();
    this.item.show();
  }

  private update(): void {
    this.item.text = statusBarText(this.controller, this.store);
    const idle = this.controller.state === 'idle';
    this.item.command = idle ? 'px4Gcs.quickConnect' : 'px4Gcs.vehicle.focus';
    this.item.tooltip = idle ? 'Quick Connect to a PX4 vehicle' : 'Show the vehicle view';
    this.item.backgroundColor = this.controller.state === 'lost'
      ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined;
  }

  dispose(): void {
    for (const s of this.subscriptions) s.dispose();
    this.item.dispose();
  }
}
