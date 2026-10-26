import { Type, type Static } from "typebox";
const text = Type.String({ minLength: 1, pattern: "\\S" });
export const CLARIFY_TOOL_NAME = "task_clarify";
export const ClarifySchema = Type.Object(
  { question: text },
  { additionalProperties: false },
);
export const TaskIdSchema = Type.String({ pattern: "^task_[A-Za-z0-9_-]+$" });
export const CreateSchema = Type.Object(
  {
    title: text,
    goal: Type.String({
      minLength: 1,
      pattern: "\\S",
      description: "Required initial Goal. At most state_event_max_chars Unicode code points from the request snapshot (bundle default 100). Put discovery details in summary; overlong goals are rejected, never truncated.",
    }),
    project_name: text,
    summary: text,
    keywords: Type.Array(text, { minItems: 1 }),
    context: Type.Optional(text),
  },
  { additionalProperties: false },
);
export const FindSchema = Type.Object(
  {
    query: text,
    keywords: Type.Optional(Type.Array(text)),
    limit: Type.Optional(
      Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER }),
    ),
  },
  { additionalProperties: false },
);
export const StatusSchema = Type.Object(
  { task_id: TaskIdSchema },
  { additionalProperties: false },
);
export const ResumeSchema = Type.Union(
  [
    StatusSchema,
    Type.Object(
      { mode: Type.Literal("latest_paused") },
      { additionalProperties: false },
    ),
  ],
  {
    type: "object",
    properties: {
      task_id: TaskIdSchema,
      mode: Type.Literal("latest_paused"),
    },
    additionalProperties: false,
  },
);
export const TaskSchema = Type.Object(
  {
    task_id: TaskIdSchema,
    title: text,
    project_name: text,
    summary: text,
    keywords: Type.Array(text, { minItems: 1 }),
    workspace: text,
    state_version: Type.Integer({ minimum: 1 }),
    status: Type.Union([
      Type.Literal("active"),
      Type.Literal("paused"),
      Type.Literal("completed"),
    ]),
    updated_at: Type.String({ format: "date-time" }),
    sessions: Type.Array(
      Type.Object(
        { session_id: text, file: text },
        { additionalProperties: false },
      ),
    ),
  },
  { additionalProperties: false },
);
export const IndexSchema = Type.Array(TaskSchema);
export type Task = Static<typeof TaskSchema>;
export type CreateInput = Static<typeof CreateSchema>;
export type FindInput = Static<typeof FindSchema>;
export type ResumeInput = Static<typeof ResumeSchema>;
