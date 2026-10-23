import { Type, type Static } from "typebox";
import type { MemoryConfig } from "../config/schema.ts";
import { stableId } from "../storage/identity.ts";
import {
  activeEntries,
  RangeSchema,
  StateIdSchema,
  type State,
} from "./model.ts";
export const StateBatchSchema = Type.Object(
  {
    task_id: Type.String({ pattern: "^task_[A-Za-z0-9_-]+$" }),
    batch_id: Type.String({ minLength: 1 }),
    evicted_range: RangeSchema,
    candidate_ids: Type.Array(StateIdSchema, {
      minItems: 1,
      uniqueItems: true,
    }),
    keep_limit: Type.Integer({ minimum: 0, maximum: Number.MAX_SAFE_INTEGER }),
    state_max_events: Type.Integer({
      minimum: 1,
      maximum: Number.MAX_SAFE_INTEGER,
    }),
    state_evict_batch: Type.Integer({
      minimum: 1,
      maximum: Number.MAX_SAFE_INTEGER,
    }),
  },
  { additionalProperties: false },
);
export type StateBatch = Static<typeof StateBatchSchema>;
export function stateBatchId(
  taskId: string,
  state: State,
  candidates: string[],
): string {
  const previous = state.events.findLast((e) => e.op === "slide_window");
  return (
    "state_" +
    stableId(
      taskId,
      previous?.op === "slide_window" ? previous.batch_id : "initial",
      JSON.stringify(candidates),
    )
  );
}
export function prepareStateBatch(
  taskId: string,
  state: State,
  config: MemoryConfig,
  tokenWarning = false,
): StateBatch | null {
  const active = activeEntries(state);
  if (
    !active.length ||
    (active.length < config.state_max_events && !tokenWarning)
  )
    return null;
  const candidates = active.slice(0, config.state_evict_batch),
    candidate_ids = candidates.map((e) => e.id);
  return {
    task_id: taskId,
    batch_id: stateBatchId(taskId, state, candidate_ids),
    evicted_range: {
      from: candidates[0]!.position,
      to: candidates.at(-1)!.position,
    },
    candidate_ids,
    keep_limit: Math.min(
      Math.floor(active.length / 10),
      config.state_keep_limit,
      candidates.length,
    ),
    state_max_events: config.state_max_events,
    state_evict_batch: config.state_evict_batch,
  };
}
export function renderStateReminder(batch: StateBatch, state: State): string {
  const facts = batch.candidate_ids.filter((id) => id.startsWith("F")),
    decisions = batch.candidate_ids.filter((id) => id.startsWith("D"));
  const bounds = [
    facts.length ? `Fact 至 ${facts.at(-1)}（含）` : "本批无 Fact",
    decisions.length
      ? `Decision 至 ${decisions.at(-1)}（含）`
      : "本批无 Decision",
  ].join("；");
  return `\n【State 窗口管理｜临时提醒】\n当前活动条目 ${activeEntries(state).length}，条数上限 ${batch.state_max_events}，条数或 token 管理线已触发。本批为最早 ${batch.candidate_ids.length} 个活动条目：${bounds}。这里只包括当前活动 State 中的上述范围。请调用 state_remain，最多保留 ${batch.keep_limit} 个本批候选；无须保留时提交 event_ids=[]。在 token 预算允许时新增认知继续正常载入，滑动可靠提交前不移除本批内容。\n`;
}
