import type { TokenCounter } from "../window/tokens.ts";
import type { TaskLocation } from "../storage/paths.ts";
import { renderState, type State } from "./model.ts";
export type StateGuard = (
  task: TaskLocation,
  next: State,
  previous?: State,
) => void | Promise<void>;
export const stateSize = (
  taskId: string,
  state: State,
  counter: TokenCounter,
) => counter.count(renderState(taskId, state)) + 32;
export function stateAdmission(
  counter: TokenCounter,
  limit: number,
): StateGuard {
  return (task, next, previous) => {
    const cost = stateSize(task.task_id, next, counter);
    if (
      cost > limit &&
      (!previous || cost > stateSize(task.task_id, previous, counter))
    )
      throw Error(
        "STATE_BUDGET_EXCEEDED: State growth rejected before commit; organize State, shorten new cognition or use a larger model",
      );
  };
}
