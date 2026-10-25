import { isDeepStrictEqual } from "node:util";
import { Check } from "typebox/value";
import {
  AppendSchema,
  UpdateGoalSchema,
  ModifyFactSchema,
  RemainSchema,
  type ModifyFactInput,
  activeEntries,
  type UpdateGoalInput,
  reduceState,
  extendState,
  cloneState,
  renderState,
  type State,
  type StateEvent,
  type StateItem,
} from "./model.ts";
import { StateBatchSchema, stateBatchId, type StateBatch } from "./window.ts";
import { atomicWrite, readOptional } from "../storage/files.ts";
import { now, stableId } from "../storage/identity.ts";
import type { MemoryPaths, TaskLocation } from "../storage/paths.ts";
import type { StateGuard } from "./budget.ts";
import { assertStateContent } from "./content.ts";
import {
  SnapshotCache,
  stateSnapshot,
  type StateSnapshot,
} from "./snapshot-cache.ts";
type EvidenceReferences = Set<string> | (() => Promise<Set<string>>);
const resolveReferences = (refs: EvidenceReferences) =>
  typeof refs === "function" ? refs() : Promise.resolve(refs);
/** Mutations require the caller to hold the Task write lock. */
export class StateStore {
  readonly paths: MemoryPaths;
  private readonly snapshots = new SnapshotCache();
  constructor(paths: MemoryPaths) {
    this.paths = paths;
  }
  private async commit(task: TaskLocation, bytes: string): Promise<void> {
    try {
      await atomicWrite(this.paths.state(task), bytes);
    } catch (error) {
      this.snapshots.delete(this.paths.state(task));
      throw Error(
        `STATE_WRITE_FAILED: ${task.task_id}; ${error instanceof Error ? error.message : "unknown write failure"}`,
      );
    }
  }
  private async load(task: TaskLocation): Promise<StateSnapshot> {
    const file = this.paths.state(task);
    try {
      const bytes = await readOptional(file);
      if (bytes === undefined) throw Error(`STATE_MISSING: ${task.task_id}`);
      if (!bytes.endsWith("\n"))
        throw Error(`CORRUPT_STATE: incomplete JSONL for ${task.task_id}`);
      const cached = this.snapshots.get(file);
      if (cached?.bytes === bytes) return cached;
      let state: State;
      try {
        const parse = (text: string): unknown[] => text.trimEnd().split("\n")
          .map((line) => JSON.parse(line) as unknown);
        state = cached?.appendable && bytes.startsWith(cached.bytes)
          && bytes.slice(cached.bytes.length).trimEnd() !== ""
          ? extendState(cached.state, parse(bytes.slice(cached.bytes.length)))
          : reduceState(parse(bytes));
      } catch {
        throw Error(`CORRUPT_STATE: ${task.task_id}`);
      }
      const snapshot = stateSnapshot(bytes, state);
      this.snapshots.set(file, snapshot);
      return snapshot;
    } catch (error) {
      this.snapshots.delete(file);
      throw error;
    }
  }
  async read(task: TaskLocation): Promise<State> {
    return cloneState((await this.load(task)).state);
  }
  private async save(
    task: TaskLocation,
    old: StateSnapshot,
    events: StateEvent[],
    guard?: StateGuard,
  ): Promise<State> {
    const next = extendState(old.state, events);
    // Admission is a validator; neither its arguments nor returned States expose cached objects.
    await guard?.(task, cloneState(next), cloneState(old.state));
    const bytes = old.bytes + next.events.slice(old.state.version)
      .map((event) => JSON.stringify(event) + "\n").join("");
    await this.commit(task, bytes);
    if (old.appendable)
      this.snapshots.set(this.paths.state(task), stateSnapshot(bytes, next, old));
    else this.snapshots.delete(this.paths.state(task));
    return cloneState(next);
  }
  async initialize(
    task: TaskLocation,
    goal: string,
    operation: string,
    guard?: StateGuard,
  ): Promise<State> {
    const old = await readOptional(this.paths.state(task));
    if (old !== undefined) {
      const state = await this.read(task);
      if (state.events[0]?.op_id !== operation)
        throw Error("TASK_ID_COLLISION");
      return state;
    }
    const event: StateEvent = {
      op_id: operation,
      op: "update_goal",
      time: now(),
      goal,
      evidence: {},
    };
    const state = reduceState([event]);
    await guard?.(task, cloneState(state));
    const bytes = JSON.stringify(event) + "\n";
    await this.commit(task, bytes);
    this.snapshots.set(this.paths.state(task), stateSnapshot(bytes, state));
    return cloneState(state);
  }
  async append(
    task: TaskLocation,
    items: StateItem[],
    operation: string,
    maxChars: number,
    refs: EvidenceReferences,
    guard?: StateGuard,
  ): Promise<State> {
    if (!Check(AppendSchema, { items })) throw Error("INVALID_STATE_APPEND");
    const snapshot = await this.load(task),
      state = snapshot.state,
      ids = items.map((_, i) => stableId(operation, i));
    const found = ids.map((id) => snapshot.operations.get(id));
    if (found.every(Boolean)) {
      if (snapshot.operations.has(stableId(operation, items.length)))
        throw Error("OPERATION_INPUT_MISMATCH");
      for (let i = 0; i < items.length; i++) {
        const item = items[i]!,
          event = found[i]!;
        if (
          event.op !==
            (item.type === "fact" ? "append_fact" : "append_decision") ||
          !isDeepStrictEqual(event.evidence, item.evidence) ||
          (event.op === "append_fact"
            ? event.fact
            : event.op === "append_decision"
              ? event.decision
              : undefined) !== item.content
        )
          throw Error("OPERATION_INPUT_MISMATCH");
      }
      return cloneState(state);
    }
    if (found.some(Boolean))
      throw Error("CORRUPT_STATE: partially committed batch");
    const evidence = new Set([
      ...(await resolveReferences(refs)),
      ...state.entries.keys(),
    ]);
    let f = state.factCount,
      d = state.decisionCount;
    const events: StateEvent[] = [];
    for (const [i, item] of items.entries()) {
      assertStateContent(item.content, maxChars, `items[${i}].content`);
      for (const ref of Object.keys(item.evidence))
        if (!evidence.has(ref)) throw Error(`INVALID_EVIDENCE: ${ref}`);
      const base = { op_id: ids[i]!, time: now(), evidence: item.evidence };
      events.push(
        item.type === "fact"
          ? { ...base, op: "append_fact", id: `F${++f}`, fact: item.content }
          : {
              ...base,
              op: "append_decision",
              id: `D${++d}`,
              decision: item.content,
            },
      );
    }
    return this.save(task, snapshot, events, guard);
  }
  async updateGoal(
    task: TaskLocation,
    input: UpdateGoalInput,
    operation: string,
    maxChars: number,
    refs: EvidenceReferences,
    guard?: StateGuard,
  ): Promise<State> {
    if (!Check(UpdateGoalSchema, input)) throw Error("INVALID_UPDATE_GOAL");
    const snapshot = await this.load(task),
      state = snapshot.state,
      previous = snapshot.operations.get(operation);
    if (previous) {
      if (
        previous.op !== "update_goal" ||
        previous.goal !== input.goal ||
        !isDeepStrictEqual(previous.evidence, input.evidence)
      )
        throw Error("OPERATION_INPUT_MISMATCH");
      return cloneState(state);
    }
    assertStateContent(input.goal, maxChars, "update_goal.goal");
    const known = new Set([
      ...(await resolveReferences(refs)),
      ...state.entries.keys(),
    ]);
    for (const ref of Object.keys(input.evidence))
      if (!known.has(ref)) throw Error(`INVALID_EVIDENCE: ${ref}`);
    const event: StateEvent = {
      op_id: operation,
      op: "update_goal",
      time: now(),
      goal: input.goal,
      evidence: input.evidence,
    };
    return this.save(task, snapshot, [event], guard);
  }
  async modifyFact(
    task: TaskLocation,
    input: ModifyFactInput,
    operation: string,
    maxChars: number,
    refs: EvidenceReferences,
    guard?: StateGuard,
  ): Promise<State> {
    if (!Check(ModifyFactSchema, input)) throw Error("INVALID_MODIFY_FACT");
    const snapshot = await this.load(task),
      state = snapshot.state,
      previous = snapshot.operations.get(operation);
    if (previous) {
      if (
        previous.op !== "modify_fact" ||
        !isDeepStrictEqual(
          [...previous.archive].sort(),
          [...input.archive].sort(),
        ) ||
        !isDeepStrictEqual(previous.append_fact, input.append_fact)
      )
        throw Error("OPERATION_INPUT_MISMATCH");
      return cloneState(state);
    }
    for (const id of input.archive) {
      const entry = state.entries.get(id);
      if (!entry) throw Error(`UNKNOWN_STATE_ID: ${id}`);
      if (entry.archived) throw Error(`ALREADY_ARCHIVED: ${id}`);
    }
    assertStateContent(input.append_fact.content, maxChars, "modify_fact.append_fact.content");
    const known = new Set([
      ...(await resolveReferences(refs)),
      ...state.entries.keys(),
    ]);
    for (const ref of Object.keys(input.append_fact.evidence))
      if (!known.has(ref)) throw Error(`INVALID_EVIDENCE: ${ref}`);
    const event: StateEvent = {
      op_id: operation,
      op: "modify_fact",
      time: now(),
      archive: input.archive,
      append_fact: input.append_fact,
    };
    return this.save(task, snapshot, [event], guard);
  }
  async remain(
    task: TaskLocation,
    batch: StateBatch,
    eventIds: string[],
    operation: string,
  ): Promise<State> {
    if (
      !Check(RemainSchema, { event_ids: eventIds }) ||
      !Check(StateBatchSchema, batch) ||
      batch.task_id !== task.task_id
    )
      throw Error("INVALID_STATE_REMAIN");
    const snapshot = await this.load(task),
      state = snapshot.state,
      selected = new Set(eventIds);
    const previous = snapshot.operations.get(operation);
    if (
      previous &&
      (previous.op !== "slide_window" || previous.batch_id !== batch.batch_id)
    )
      throw Error("OPERATION_INPUT_MISMATCH");
    const committed = snapshot.batches.get(batch.batch_id);
    if (committed?.op === "slide_window") {
      if (
        !isDeepStrictEqual(
          [...committed.retained_ids].sort(),
          [...eventIds].sort(),
        )
      )
        throw Error(
          "STATE_BATCH_ALREADY_COMMITTED: different retention decision; refresh State",
        );
      return cloneState(state);
    }
    if (eventIds.length > batch.keep_limit)
      throw Error("STATE_KEEP_LIMIT_EXCEEDED");
    if (eventIds.some((id) => !batch.candidate_ids.includes(id)))
      throw Error("INVALID_STATE_CANDIDATE");
    const candidates = activeEntries(state).slice(
      0,
      batch.candidate_ids.length,
    );
    if (
      !isDeepStrictEqual(
        candidates.map((e) => e.id),
        batch.candidate_ids,
      ) ||
      candidates[0]?.position !== batch.evicted_range.from ||
      candidates.at(-1)?.position !== batch.evicted_range.to ||
      stateBatchId(task.task_id, state, batch.candidate_ids) !== batch.batch_id
    )
      throw Error("STALE_STATE_BATCH: candidates changed; refresh State");
    const event: StateEvent = {
      op_id: operation,
      op: "slide_window",
      time: now(),
      batch_id: batch.batch_id,
      evicted_range: batch.evicted_range,
      retained_ids: batch.candidate_ids.filter((id) => selected.has(id)),
      status: "committed",
    };
    return this.save(task, snapshot, [event]);
  }
  async writeView(task: TaskLocation, state: State): Promise<string> {
    const text = renderState(task.task_id, state);
    try {
      await atomicWrite(this.paths.view(task), text);
    } catch {
      throw Error(
        `PARTIAL_COMMIT: ${task.task_id} State v${state.version} committed; state.md failed`,
      );
    }
    return text;
  }
}
