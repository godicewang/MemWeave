import { Type, type Static } from "typebox";
const id = () => Type.String({ minLength: 1 });
const integer = () =>
  Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER });
const nullable = () => Type.Union([id(), Type.Null()]);
export const WINDOW_TYPE = "memweave.window.v1";
export const SetWindowSchema = Type.Object(
  { turns: integer(), evict_turns: Type.Optional(integer()) },
  { additionalProperties: false },
);
export type SetWindowInput = Static<typeof SetWindowSchema>;
export const WindowSchema = Type.Object(
  {
    stage: Type.Union([
      Type.Literal("prepare"),
      Type.Literal("commit"),
      Type.Literal("reset"),
    ]),
    recent_turns: integer(),
    evict_turns: integer(),
    boundary_entry_id: nullable(),
    pending: Type.Array(
      Type.Object(
        {
          batch_id: id(),
          candidate_event_ids: Type.Array(id(), {
            minItems: 1,
            uniqueItems: true,
          }),
        },
        { additionalProperties: false },
      ),
    ),
    request_anchor_entry_id: nullable(),
    completed_by: nullable(),
  },
  { additionalProperties: false },
);
export type WindowMetadata = Static<typeof WindowSchema>;
