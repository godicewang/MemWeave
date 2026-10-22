import { Type, type Static } from "typebox";
import { Check } from "typebox/value";
import { StatusSchema, TaskIdSchema } from "../task/model.ts";
import { StateIdSchema, type State } from "./model.ts";
const count = () =>
  Type.Integer({ minimum: 0, maximum: Number.MAX_SAFE_INTEGER });
const HistoryInputSchema = Type.Object(
  {
    task_id: TaskIdSchema,
    event_ids: Type.Array(StateIdSchema, { minItems: 1, maxItems: 50 }),
    max_total_chars: Type.Optional(
      Type.Integer({ minimum: 1, maximum: 50000 }),
    ),
  },
  { additionalProperties: false },
);
// Providers require an object root; retain the union's exact input validation.
export const StateReadSchema = Type.Union([StatusSchema, HistoryInputSchema], {
  type: "object",
  properties: HistoryInputSchema.properties,
  required: ["task_id"],
  additionalProperties: false,
});
export type StateReadInput = Static<typeof StateReadSchema>;
type HistoryInput = Extract<StateReadInput, { event_ids: string[] }>;
const HistoryItemSchema = Type.Object(
  {
    id: StateIdSchema,
    status: Type.Union([
      Type.Literal("ok"),
      Type.Literal("not_found"),
      Type.Literal("budget_exhausted"),
    ]),
    kind: Type.Optional(
      Type.Union([Type.Literal("fact"), Type.Literal("decision")]),
    ),
    archived: Type.Optional(Type.Boolean()),
    in_window: Type.Optional(Type.Boolean()),
    content: Type.String(),
    evidence: Type.Record(
      Type.String({ pattern: "^[UATFDR][1-9][0-9]*$" }),
      Type.String(),
    ),
    total_chars: Type.Union([count(), Type.Null()]),
    returned_chars: count(),
    truncated: Type.Boolean(),
  },
  { additionalProperties: false },
);
const HistoryReadSchema = Type.Object(
  {
    task_id: TaskIdSchema,
    state_version: Type.Integer({
      minimum: 1,
      maximum: Number.MAX_SAFE_INTEGER,
    }),
    items: Type.Array(HistoryItemSchema, { minItems: 1, maxItems: 50 }),
    total_chars: Type.Integer({ minimum: 0, maximum: 50000 }),
  },
  { additionalProperties: false },
);
export type HistoricalStateRead = Static<typeof HistoryReadSchema>;
function length(text: string) {
  let size = 0;
  for (const _point of text) size++;
  return size;
}
function chars(item: { content: string; evidence: Record<string, string> }) {
  return (
    length(item.content) +
    Object.entries(item.evidence).reduce(
      (sum, [ref, text]) => sum + length(ref) + length(text),
      0,
    )
  );
}
function prefix(text: string, budget: number) {
  let content = "",
    used = 0;
  for (const point of text) {
    if (used === budget) break;
    content += point;
    used++;
  }
  return { content, used };
}
/** Reads replayed history only; never mutates the State or expands evidence recursively. */
export function readHistoricalState(
  taskId: string,
  state: State,
  input: Omit<HistoryInput, "task_id">,
): HistoricalStateRead {
  if (!Check(StateReadSchema, { ...input, task_id: taskId }))
    throw Error("INVALID_STATE_READ");
  const budget = input.max_total_chars ?? 8000;
  let remaining = budget;
  const items: HistoricalStateRead["items"] = input.event_ids.map((id) => {
    const entry = state.entries.get(id);
    if (!entry)
      return {
        id,
        status: "not_found",
        content: "",
        evidence: {},
        total_chars: null,
        returned_chars: 0,
        truncated: true,
      };
    const total_chars = chars(entry),
      exhausted = remaining === 0;
    const body = prefix(entry.content, remaining);
    remaining -= body.used;
    const evidence: Record<string, string> = {};
    for (const [ref, text] of Object.entries(entry.evidence)) {
      const key = length(ref);
      if (remaining < key) break;
      remaining -= key;
      const value = prefix(text, remaining);
      remaining -= value.used;
      evidence[ref] = value.content;
      if (value.used < length(text)) break;
    }
    const returned_chars = chars({ content: body.content, evidence });
    return {
      id,
      status: exhausted ? "budget_exhausted" : "ok",
      kind: entry.kind,
      archived: entry.archived,
      in_window: entry.active && !entry.archived,
      content: body.content,
      evidence,
      total_chars,
      returned_chars,
      truncated: returned_chars !== total_chars,
    };
  });
  return {
    task_id: taskId,
    state_version: state.version,
    items,
    total_chars: budget - remaining,
  };
}
/** Reuse the existing machine range envelope; verify the actual body before granting X. */
export function historyReadRanges(value: unknown) {
  if (
    !Check(HistoryReadSchema, value) ||
    value.total_chars !==
      value.items.reduce((sum, item) => sum + item.returned_chars, 0)
  )
    throw Error("INVALID_STATE_READ_RESULT");
  return value.items.map((item) => {
    if (
      chars(item) !== item.returned_chars ||
      (item.status === "not_found"
        ? item.total_chars !== null ||
          item.returned_chars !== 0 ||
          !item.truncated
        : item.kind === undefined ||
          item.archived === undefined ||
          item.in_window === undefined ||
          item.total_chars === null ||
          item.total_chars < item.returned_chars ||
          item.truncated !== (item.total_chars !== item.returned_chars))
    )
      throw Error("INVALID_STATE_READ_RESULT");
    return {
      ref: item.id,
      source_task_id: value.task_id,
      offset: 0,
      returned_chars: item.returned_chars,
      range_complete: item.status === "ok" && !item.truncated,
      source_complete: item.total_chars !== null,
      status: item.status,
    };
  });
}
