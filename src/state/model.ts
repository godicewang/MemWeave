import { Type, type Static } from "typebox";
import { Check } from "typebox/value";
const text = Type.String({ minLength: 1, pattern: "\\S" });
export const StateIdSchema = Type.String({ pattern: "^[FD][1-9][0-9]*$" });
export const EvidenceSchema = Type.Record(
  Type.String({ pattern: "^[UATFDR][1-9][0-9]*$" }),
  text,
  { minProperties: 1 },
);
const factInput = Type.Object(
  { content: text, evidence: EvidenceSchema },
  { additionalProperties: false },
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
export const UpdateGoalSchema = Type.Object(
  {
    goal: text,
    summary: text,
    keywords: Type.Array(text, { minItems: 1 }),
    evidence: EvidenceSchema,
    project_name: Type.Optional(text),
  },
  { additionalProperties: false },
);
export const ModifyFactSchema = Type.Object(
  {
    archive: Type.Array(StateIdSchema, { minItems: 1, uniqueItems: true }),
    append_fact: factInput,
  },
  { additionalProperties: false },
);
export const RemainSchema = Type.Object(
  { event_ids: Type.Array(StateIdSchema, { uniqueItems: true }) },
  { additionalProperties: false },
);
export const RangeSchema = Type.Object(
  {
    from: Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER }),
    to: Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER }),
  },
  { additionalProperties: false },
);
export type UpdateGoalInput = Static<typeof UpdateGoalSchema>;
export type ModifyFactInput = Static<typeof ModifyFactSchema>;
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
  Type.Object(
    {
      ...base,
      op: Type.Literal("modify_fact"),
      archive: Type.Array(StateIdSchema, { minItems: 1, uniqueItems: true }),
      append_fact: factInput,
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      ...base,
      op: Type.Literal("slide_window"),
      batch_id: text,
      evicted_range: RangeSchema,
      retained_ids: Type.Array(StateIdSchema, { uniqueItems: true }),
      status: Type.Literal("committed"),
    },
    { additionalProperties: false },
  ),
]);
export type StateEvent = Static<typeof EventSchema>;
export interface StateEntry {
  id: string;
  kind: "fact" | "decision";
  content: string;
  evidence: Record<string, string>;
  position: number;
  archived: boolean;
  active: boolean;
}
export interface State {
  version: number;
  goal: string;
  facts: StateEntry[];
  decisions: StateEntry[];
  entries: Map<string, StateEntry>;
  factCount: number;
  decisionCount: number;
  events: StateEvent[];
}
export function activeEntries(state: State): StateEntry[] {
  return [...state.entries.values()].filter((e) => e.active && !e.archived);
}
export function reduceState(value: unknown[]): State {
  const state: State = {
    version: 0,
    goal: "",
    facts: [],
    decisions: [],
    entries: new Map(),
    factCount: 0,
    decisionCount: 0,
    events: [],
  };
  const operations = new Set<string>(),
    batches = new Set<string>();
  function add(
    kind: "fact" | "decision",
    content: string,
    evidence: Record<string, string>,
    id?: string,
  ) {
    const expected =
      kind === "fact" ? `F${++state.factCount}` : `D${++state.decisionCount}`;
    if (id !== undefined && id !== expected)
      throw Error("CORRUPT_STATE: non-contiguous State IDs");
    state.entries.set(expected, {
      id: expected,
      kind,
      content,
      evidence,
      position: state.version + 1,
      archived: false,
      active: true,
    });
  }
  for (const event of value) {
    if (
      !Check(EventSchema, event) ||
      operations.has(event.op_id) ||
      (!state.version && event.op !== "update_goal")
    )
      throw Error("CORRUPT_STATE: invalid or duplicated operation");
    operations.add(event.op_id);
    switch (event.op) {
      case "update_goal":
        state.goal = event.goal;
        break;
      case "append_fact":
        add("fact", event.fact, event.evidence, event.id);
        break;
      case "append_decision":
        add("decision", event.decision, event.evidence, event.id);
        break;
      case "modify_fact":
        for (const id of event.archive) {
          const entry = state.entries.get(id);
          if (!entry || entry.archived)
            throw Error("CORRUPT_STATE: invalid archive");
          entry.archived = true;
          entry.active = false;
        }
        add("fact", event.append_fact.content, event.append_fact.evidence);
        break;
      case "slide_window": {
        const active = activeEntries(state),
          range = event.evicted_range,
          candidates = active.filter(
            (e) => e.position >= range.from && e.position <= range.to,
          );
        if (
          batches.has(event.batch_id) ||
          range.from > range.to ||
          range.to > state.version ||
          !candidates.length ||
          candidates[0] !== active[0] ||
          candidates[0]?.position !== range.from ||
          candidates.at(-1)?.position !== range.to ||
          event.retained_ids.some((id) => !candidates.some((e) => e.id === id))
        )
          throw Error("CORRUPT_STATE: invalid window slide");
        batches.add(event.batch_id);
        const retained = new Set(event.retained_ids);
        for (const entry of candidates)
          if (!retained.has(entry.id)) entry.active = false;
        break;
      }
    }
    state.events.push(event);
    state.version++;
  }
  if (!state.goal) throw Error("CORRUPT_STATE: initial Goal is missing");
  const active = activeEntries(state);
  state.facts = active.filter((e) => e.kind === "fact");
  state.decisions = active.filter((e) => e.kind === "decision");
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
