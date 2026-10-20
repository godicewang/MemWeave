import { isDeepStrictEqual } from "node:util";
import { Check } from "typebox/value";
import {
  AppendSchema,
  reduceState,
  renderState,
  type State,
  type StateEvent,
  type StateItem,
} from "./model.ts";
import { atomicWrite, readOptional } from "../storage/files.ts";
import { now, stableId } from "../storage/identity.ts";
import type { MemoryPaths, TaskLocation } from "../storage/paths.ts";
/** Mutations require the caller to hold the Task write lock. */
export class StateStore {
  readonly paths: MemoryPaths;
  constructor(paths: MemoryPaths) {
    this.paths = paths;
  }
  private async commit(task: TaskLocation, bytes: string): Promise<void> {
    try {
      await atomicWrite(this.paths.state(task), bytes);
    } catch (error) {
      throw Error(
        `STATE_WRITE_FAILED: ${task.task_id}; ${error instanceof Error ? error.message : "unknown write failure"}`,
      );
    }
  }
  async read(task: TaskLocation): Promise<State> {
    const bytes = await readOptional(this.paths.state(task));
    if (bytes === undefined) throw Error(`STATE_MISSING: ${task.task_id}`);
    if (!bytes.endsWith("\n"))
      throw Error(`CORRUPT_STATE: incomplete JSONL for ${task.task_id}`);
    try {
      return reduceState(
        bytes
          .trimEnd()
          .split("\n")
          .map((line) => JSON.parse(line) as unknown),
      );
    } catch {
      throw Error(`CORRUPT_STATE: ${task.task_id}`);
    }
  }
  async initialize(
    task: TaskLocation,
    goal: string,
    operation: string,
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
    await this.commit(task, JSON.stringify(event) + "\n");
    return state;
  }
  async append(
    task: TaskLocation,
    items: StateItem[],
    operation: string,
    maxChars: number,
    refs: Set<string>,
  ): Promise<State> {
    if (!Check(AppendSchema, { items })) throw Error("INVALID_STATE_APPEND");
    const state = await this.read(task),
      ids = items.map((_, i) => stableId(operation, i));
    const found = ids.map((id) => state.events.find((e) => e.op_id === id));
    if (found.every(Boolean)) {
      if (
        state.events.some(
          (event) => event.op_id === stableId(operation, items.length),
        )
      )
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
      return state;
    }
    if (found.some(Boolean))
      throw Error("CORRUPT_STATE: partially committed batch");
    const evidence = new Set([
      ...refs,
      ...state.facts.map((e) => e.id),
      ...state.decisions.map((e) => e.id),
    ]);
    let f = state.facts.length,
      d = state.decisions.length;
    const events: StateEvent[] = [];
    for (const [i, item] of items.entries()) {
      if ([...item.content].length > maxChars)
        throw Error("STATE_CONTENT_TOO_LONG");
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
    const bytes = (await readOptional(this.paths.state(task)))!;
    const result = reduceState([...state.events, ...events]);
    await this.commit(
      task,
      bytes + events.map((e) => JSON.stringify(e) + "\n").join(""),
    );
    return result;
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
