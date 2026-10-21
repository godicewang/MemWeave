import { Type, type Static } from "typebox";
import { Check } from "typebox/value";
const text = Type.String({ minLength: 1, pattern: "\\S" });
export const EvidenceSchema = Type.Record(
  Type.String({ pattern: "^[UATFDR][1-9][0-9]*$" }),
  text,
  { minProperties: 1 },
);
export const AppendSchema = Type.Object(
  {
    items: Type.Array(
      Type.Object(
        {
          type: Type.Union([Type.Literal("fact"), Type.Literal("decision")]),
          content: text,
          evidence: EvidenceSchema,
        },
        { additionalProperties: false },
      ),
      { minItems: 1 },
    ),
  },
  { additionalProperties: false },
);
export const UpdateGoalSchema = Type.Object({
  goal:text,summary:text,keywords:Type.Array(text,{minItems:1}),evidence:EvidenceSchema,project_name:Type.Optional(text),
},{additionalProperties:false});
export type UpdateGoalInput = Static<typeof UpdateGoalSchema>;
export type StateItem = Static<typeof AppendSchema>["items"][number];
const base = { op_id: text, time: text };
export const EventSchema = Type.Union([
  Type.Object(
    {
      ...base,
      op: Type.Literal("update_goal"),
      goal: text,
      evidence: Type.Record(
        Type.String({ pattern: "^[UATFDR][1-9][0-9]*$" }),
        text,
      ),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      ...base,
      op: Type.Literal("append_fact"),
      id: Type.String({ pattern: "^F[1-9][0-9]*$" }),
      fact: text,
      evidence: EvidenceSchema,
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      ...base,
      op: Type.Literal("append_decision"),
      id: Type.String({ pattern: "^D[1-9][0-9]*$" }),
      decision: text,
      evidence: EvidenceSchema,
    },
    { additionalProperties: false },
  ),
]);
export type StateEvent = Static<typeof EventSchema>;
export interface StateEntry {
  id: string;
  content: string;
  evidence: Record<string, string>;
}
export interface State {
  version: number;
  goal: string;
  facts: StateEntry[];
  decisions: StateEntry[];
  events: StateEvent[];
}
export function reduceState(value: unknown[]): State {
  const state: State = {
    version: 0,
    goal: "",
    facts: [],
    decisions: [],
    events: [],
  };
  const operations = new Set<string>();
  for (const event of value) {
    if (!Check(EventSchema, event) || operations.has(event.op_id))
      throw Error("CORRUPT_STATE: invalid or duplicated operation");
    operations.add(event.op_id);
    if (event.op === "update_goal") state.goal = event.goal;
    else {
      const list = event.op === "append_fact" ? state.facts : state.decisions;
      const prefix = event.op === "append_fact" ? "F" : "D";
      if (event.id !== `${prefix}${list.length + 1}`)
        throw Error("CORRUPT_STATE: non-contiguous State IDs");
      list.push({
        id: event.id,
        content: event.op === "append_fact" ? event.fact : event.decision,
        evidence: event.evidence,
      });
    }
    state.events.push(event);
    state.version++;
  }
  if (!state.goal) throw Error("CORRUPT_STATE: initial Goal is missing");
  return state;
}
export function renderState(taskId: string, state: State): string {
  const block = (entries: StateEntry[]) =>
    entries
      .map(
        (e) =>
          `${e.id} ${e.content}\ne: [${Object.keys(e.evidence).join(", ")}]`,
      )
      .join("\n\n");
  return `# Symbolic State\n\ntask_id: ${taskId}\nstate_version: ${state.version}\n\n## Goal\n\n${state.goal}\n\n## Facts\n\n${block(state.facts)}\n\n## Decisions\n\n${block(state.decisions)}\n`;
}
