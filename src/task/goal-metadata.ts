import { Check } from "typebox/value";
import { CreateSchema, type Task } from "./model.ts";
import { UpdateGoalSchema, type State } from "../state/model.ts";
import type { SessionMemory } from "../pi/session-memory.ts";
import { stableId } from "../storage/identity.ts";

interface GoalMetadata {
  summary: string;
  keywords: string[];
  project_name: string;
  time: string;
}
/** Discovery metadata remains in the index. Native invocation arguments repair partial index commits. */
export class GoalMetadataResolver {
  readonly memory: SessionMemory;
  readonly cache = new Map<
    string,
    { operation: string; metadata: GoalMetadata }
  >();
  constructor(memory: SessionMemory) {
    this.memory = memory;
  }
  async current(task: Task, state: State): Promise<GoalMetadata | null> {
    const goals = state.events.filter((e) => e.op === "update_goal");
    if (goals.length < 2) return null;
    const latest = goals.at(-1)!;
    const cached = this.cache.get(task.task_id);
    if (cached?.operation === latest.op_id) return cached.metadata;
    const calls = new Map<string, unknown>();
    for (const source of task.sessions) {
      const view = await this.memory.files.readView(
        source.file,
        source.session_id,
      );
      for (const entry of view.entries) {
        if (entry.type !== "message" || entry.message.role !== "assistant")
          continue;
        for (const call of entry.message.content)
          if (
            call.type === "toolCall" &&
            (call.name === "update_goal" || call.name === "task_create")
          )
            calls.set(
              stableId(task.task_id, source.session_id, entry.id, call.id),
              call.arguments,
            );
      }
    }
    const initial = calls.get(goals[0]!.op_id);
    if (!Check(CreateSchema, initial) || initial.goal !== goals[0]!.goal)
      throw Error(`GOAL_METADATA_SOURCE_MISSING: ${task.task_id}`);
    let project = initial.project_name,
      metadata: GoalMetadata | null = null;
    for (const goal of goals.slice(1)) {
      const input = calls.get(goal.op_id);
      if (!Check(UpdateGoalSchema, input) || input.goal !== goal.goal)
        throw Error(`GOAL_METADATA_SOURCE_MISSING: ${task.task_id}`);
      if (input.project_name !== undefined) project = input.project_name;
      metadata = {
        summary: input.summary,
        keywords: input.keywords,
        project_name: project,
        time: goal.time,
      };
    }
    this.cache.set(task.task_id, {
      operation: latest.op_id,
      metadata: metadata!,
    });
    return metadata;
  }
}
