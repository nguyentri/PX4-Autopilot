// Reference-counted stream demand. Views (owners) acquire the MAVLink messages
// they need while visible; the first owner of a message raises its rate with
// `stream_request`, the last one to leave restores it with `stream_release`.
// A refused request (no current interval on the vehicle) leaves the stream
// alone and is reported once per owner. No `vscode` import.

export interface StreamNeed {
  message: number;
  intervalUs: number;
}

export interface StreamPort {
  request(message: number, intervalUs: number): Promise<void>;
  release(message: number): Promise<void>;
}

type Outcome = 'raised' | 'refused' | 'pending';

export interface DemandNote {
  owner: string;
  message: number;
  outcome: 'raised' | 'refused';
  reason?: string;
}

export class StreamDemand {
  private readonly owners = new Map<string, Set<number>>();
  private readonly counts = new Map<number, number>();
  private readonly outcome = new Map<number, Outcome>();
  private readonly inflight = new Map<number, Promise<void>>();

  constructor(private readonly port: StreamPort, private readonly note: (n: DemandNote) => void = () => {}) {}

  /** Owner `owner` needs every message in `needs` (replaces its previous set). */
  async acquire(owner: string, needs: StreamNeed[]): Promise<void> {
    const held = this.owners.get(owner);
    if (held && held.size === new Set(needs.map((n) => n.message)).size && needs.every((n) => held.has(n.message))) return;
    await this.releaseOwner(owner);
    const mine = new Set<number>();
    this.owners.set(owner, mine);
    const work: Promise<void>[] = [];
    for (const need of needs) {
      if (mine.has(need.message)) continue;
      mine.add(need.message);
      const count = (this.counts.get(need.message) ?? 0) + 1;
      this.counts.set(need.message, count);
      if (count === 1) work.push(this.raise(owner, need));
      else work.push(this.report(owner, need.message));
    }
    await Promise.all(work);
  }

  async releaseOwner(owner: string): Promise<void> {
    const mine = this.owners.get(owner);
    if (!mine) return;
    this.owners.delete(owner);
    const work: Promise<void>[] = [];
    for (const message of mine) {
      const count = (this.counts.get(message) ?? 1) - 1;
      if (count > 0) {
        this.counts.set(message, count);
        continue;
      }
      this.counts.delete(message);
      work.push(this.lower(message));
    }
    await Promise.all(work);
  }

  /** The connection ended: the sidecar restored every interval itself; forget all counts. */
  reset(): void {
    this.owners.clear();
    this.counts.clear();
    this.outcome.clear();
    this.inflight.clear();
  }

  refCount(message: number): number {
    return this.counts.get(message) ?? 0;
  }

  private async raise(owner: string, need: StreamNeed): Promise<void> {
    this.outcome.set(need.message, 'pending');
    const attempt = this.port.request(need.message, need.intervalUs).then(
      () => { this.outcome.set(need.message, 'raised'); this.note({ owner, message: need.message, outcome: 'raised' }); },
      (error: unknown) => {
        this.outcome.set(need.message, 'refused');
        this.note({ owner, message: need.message, outcome: 'refused', reason: errorText(error) });
      });
    this.inflight.set(need.message, attempt);
    await attempt;
    this.inflight.delete(need.message);
  }

  private async report(owner: string, message: number): Promise<void> {
    await this.inflight.get(message);
    const state = this.outcome.get(message);
    if (state === 'raised' || state === 'refused') this.note({ owner, message, outcome: state });
  }

  private async lower(message: number): Promise<void> {
    await this.inflight.get(message);
    const state = this.outcome.get(message);
    this.outcome.delete(message);
    if (state !== 'raised') return;
    try {
      await this.port.release(message);
    } catch {
      // The sidecar restores every remaining interval on disconnect anyway.
    }
  }
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
