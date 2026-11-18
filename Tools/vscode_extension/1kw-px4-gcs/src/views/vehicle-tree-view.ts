// The "Vehicle" tree: link, identity, mode, armed, battery, GPS and foreign
// traffic, and the .tlog recording (start/stop inline). Empty while idle so
// the welcome view (Quick Connect) shows.
import * as path from 'path';
import * as vscode from 'vscode';
import { ConnectionController } from '../connection/connection-controller';
import { RecordingView } from '../dashboard/dashboard-messages';
import { VehicleStateStore } from '../vehicle/vehicle-state-store';

const MAV_TYPES: Record<number, string> = {
  1: 'fixed wing', 2: 'quadrotor', 4: 'helicopter', 10: 'ground rover', 12: 'submarine', 13: 'hexarotor',
  14: 'octorotor', 15: 'tricopter', 19: 'VTOL', 20: 'VTOL', 21: 'VTOL', 22: 'VTOL',
};
const GPS_FIX = ['no GPS', 'no fix', '2D fix', '3D fix', 'DGPS', 'RTK float', 'RTK fixed', 'static', 'PPP'];

export interface VehicleRow {
  id: string;
  label: string;
  value: string;
  icon: string;
  contextValue?: string;
}

function fixed(value: unknown, digits: number, unit: string): string | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(digits)} ${unit}` : undefined;
}

/** Rows shown for the current state; exported for the tests. */
export function vehicleRows(controller: ConnectionController, store: VehicleStateStore,
  recording: RecordingView = { active: false }): VehicleRow[] {
  const state = controller.state;
  if (state === 'idle') return [];
  const link = controller.link;
  const where = link?.transport === 'udp' ? `udp ${link.host}:${link.udpPort}`
    : link?.port ? `${link.port}${link.baud ? ` @ ${link.baud}` : ''}` : '';
  const rows: VehicleRow[] = [{
    id: 'link', label: 'Link', value: [state, where].filter(Boolean).join(' · '),
    icon: state === 'connected' ? 'plug' : state === 'lost' ? 'warning' : 'sync~spin',
    contextValue: state === 'connected' || state === 'lost' ? 'px4Gcs.link.active' : 'px4Gcs.link.pending',
  }];
  if (link?.systemId !== undefined) {
    const type = MAV_TYPES[store.heartbeat?.vehicleType ?? link.vehicleType ?? -1] ?? `type ${link.vehicleType}`;
    rows.push({ id: 'identity', label: 'Vehicle', value: `system ${link.systemId} · PX4 · ${type}`, icon: 'rocket' });
  }
  const hb = store.heartbeat;
  if (hb) {
    rows.push({ id: 'mode', label: 'Mode', value: hb.mode, icon: 'compass' });
    rows.push({ id: 'armed', label: 'Armed', value: hb.armed ? 'ARMED' : 'disarmed', icon: hb.armed ? 'flame' : 'shield' });
  }
  const battery = store.get<{ voltage?: number; current?: number; remaining?: number }>('battery');
  if (battery) {
    const parts = [fixed(battery.voltage, 2, 'V'), fixed(battery.current, 1, 'A'),
      typeof battery.remaining === 'number' ? `${battery.remaining} %` : undefined].filter(Boolean);
    rows.push({ id: 'battery', label: 'Battery', value: parts.join(' · ') || 'no data', icon: 'zap' });
  }
  const gps = store.get<{ fixType?: number; satellites?: number | null; eph?: number | null }>('gps');
  if (gps) {
    const parts = [GPS_FIX[gps.fixType ?? 0] ?? `fix ${gps.fixType}`,
      typeof gps.satellites === 'number' ? `${gps.satellites} sats` : undefined, fixed(gps.eph, 1, 'm hacc')];
    rows.push({ id: 'gps', label: 'GPS', value: parts.filter(Boolean).join(' · '), icon: 'location' });
  }
  if (state === 'connected' || recording.active) {
    rows.push(recording.active
      ? { id: 'recording', label: 'Recording', value: path.basename(recording.path ?? ''), icon: 'record',
        contextValue: 'px4Gcs.recording.on' }
      : { id: 'recording', label: 'Recording', value: 'off', icon: 'circle-outline', contextValue: 'px4Gcs.recording.off' });
  }
  if (link?.foreignFrames) {
    rows.push({ id: 'foreign', label: 'Ignored traffic', value: `${link.foreignFrames} frames from other systems`, icon: 'filter' });
  }
  return rows;
}

export class VehicleTreeProvider implements vscode.TreeDataProvider<VehicleRow>, vscode.Disposable {
  private readonly emitter = new vscode.EventEmitter<VehicleRow | undefined>();
  readonly onDidChangeTreeData = this.emitter.event;
  private readonly subscriptions: { dispose(): void }[];

  constructor(private readonly controller: ConnectionController, private readonly store: VehicleStateStore,
    private readonly recording: () => RecordingView = () => ({ active: false })) {
    this.subscriptions = [
      controller.onDidChangeState(() => this.emitter.fire(undefined)),
      store.onDidChange(() => this.emitter.fire(undefined)),
    ];
  }

  getChildren(element?: VehicleRow): VehicleRow[] {
    return element ? [] : vehicleRows(this.controller, this.store, this.recording());
  }

  refresh(): void {
    this.emitter.fire(undefined);
  }

  getTreeItem(row: VehicleRow): vscode.TreeItem {
    const item = new vscode.TreeItem(row.label, vscode.TreeItemCollapsibleState.None);
    item.id = row.id;
    item.description = this.store.stale && row.id !== 'link' ? `${row.value} (stale)` : row.value;
    item.iconPath = new vscode.ThemeIcon(row.icon);
    item.contextValue = row.contextValue;
    return item;
  }

  dispose(): void {
    for (const s of this.subscriptions) s.dispose();
    this.emitter.dispose();
  }
}
