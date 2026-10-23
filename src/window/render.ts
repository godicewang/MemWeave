import type { RequestMessages } from "../pi/request-lifecycle.ts";
import type { WindowMetadata } from "./model.ts";
export function windowReminder(
  pending: WindowMetadata["pending"],
  boundary: string,
): string {
  return pending.length
    ? `Recent Window 移出提醒：截至 ${boundary} 的 ${pending.reduce((n, b) => n + b.candidate_event_ids.length, 0)} 个交互事件将退出窗口（${pending.length} 批）。如有影响后续任务的重要认知，请使用 state_append 保存；否则无需更新 State。原文仍可按已有引用回读。`
    : "";
}
/** Transient native custom messages: Pi converts them to user; never append them to Session. */
export function stateInsert(
  messages: RequestMessages,
  state: string,
  reminder: string,
): RequestMessages {
  const result = [...messages];
  if (reminder)
    result.push({
      role: "custom",
      customType: "memweave.window.reminder",
      content: reminder,
      display: false,
      timestamp: 0,
    });
  if (state)
    result.push({
      role: "custom",
      customType: "memweave.state",
      content: state,
      display: false,
      timestamp: 0,
    });
  return result;
}
