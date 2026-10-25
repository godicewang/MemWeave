import type { State, StateEvent } from "./model.ts";

export interface StateSnapshot {
  readonly bytes: string;
  readonly state: State;
  readonly operations: Map<string, StateEvent>;
  readonly batches: Map<string, StateEvent>;
  readonly appendable: boolean;
  readonly estimatedBytes: number;
}
export function stateSnapshot(
  bytes: string,
  state: State,
  previous?: StateSnapshot,
): StateSnapshot {
  const operations = new Map(previous?.operations),
    batches = new Map(previous?.batches);
  for (let i = previous?.state.version ?? 0; i < state.events.length; i++) {
    const event = state.events[i]!;
    operations.set(event.op_id, event);
    if (event.op === "slide_window") batches.set(event.batch_id, event);
  }
  // The old parser permits trailing whitespace, but it must not become an interior record.
  const tail = bytes.slice(bytes.trimEnd().length);
  return {
    bytes, state, operations, batches,
    appendable: /^[ \t\r]*\n$/.test(tail),
    estimatedBytes: Buffer.byteLength(bytes, "utf8") * 4
      + state.events.length * 1024 + state.entries.size * 256,
  };
}
/** Internal resource ceiling, not a persisted or user-facing configuration contract. */
export class SnapshotCache {
  readonly maxTasks: number;
  readonly maxBytes: number;
  private readonly snapshots = new Map<string, StateSnapshot>();
  private usedBytes = 0;
  constructor(maxTasks = 4, maxBytes = 128 * 1024 * 1024) {
    this.maxTasks = maxTasks;
    this.maxBytes = maxBytes;
  }
  get size(): number {
    return this.snapshots.size;
  }
  get bytes(): number {
    return this.usedBytes;
  }
  get(key: string): StateSnapshot | undefined {
    const value = this.snapshots.get(key);
    if (value) {
      this.snapshots.delete(key);
      this.snapshots.set(key, value);
    }
    return value;
  }
  delete(key: string): void {
    const previous = this.snapshots.get(key);
    if (previous) this.usedBytes -= previous.estimatedBytes;
    this.snapshots.delete(key);
  }
  set(key: string, value: StateSnapshot): void {
    this.delete(key);
    if (value.estimatedBytes > this.maxBytes) return;
    while (
      this.snapshots.size >= this.maxTasks
      || this.usedBytes + value.estimatedBytes > this.maxBytes
    ) {
      const oldest = this.snapshots.keys().next().value;
      if (oldest === undefined) break;
      this.delete(oldest);
    }
    this.snapshots.set(key, value);
    this.usedBytes += value.estimatedBytes;
  }
}
