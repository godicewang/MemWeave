import { CONFIG_LIMITS } from "../config/defaults.ts";
import { Type, type Static } from "typebox";
import { TaskIdSchema } from "../task/model.ts";

const integer = (minimum: number) =>
  Type.Integer({ minimum, maximum: Number.MAX_SAFE_INTEGER });
export const OriginalRefSchema = Type.String({ pattern: "^[UAT][1-9][0-9]*$" });
export const MemoryReadSchema = Type.Object(
  {
    items: Type.Array(
      Type.Object(
        {
          ref: Type.String({ pattern: "^[UATR][1-9][0-9]*$" }),
          task_id: Type.Optional(TaskIdSchema),
          offset: Type.Optional(integer(0)),
          limit: Type.Optional(integer(1)),
        },
        { additionalProperties: false },
      ),
      { minItems: 1 },
    ),
    max_total_chars: Type.Optional(
      Type.Integer({ minimum: 1, maximum: CONFIG_LIMITS.read_chars }),
    ),
  },
  { additionalProperties: false },
);
export type MemoryReadInput = Static<typeof MemoryReadSchema>;
export const ALIAS_TYPE = "memweave.aliases.v1",
  ORIGINAL_TYPE = "memweave.originals.v1";
const AliasSchema = Type.Object(
  {
    ref: Type.String({ pattern: "^R[1-9][0-9]*$" }),
    source_task_id: TaskIdSchema,
    source_ref: OriginalRefSchema,
    part_index: Type.Optional(integer(0)),
  },
  { additionalProperties: false },
);
export const AliasesSchema = Type.Object(
  { task_id: TaskIdSchema, bindings: Type.Array(AliasSchema, { minItems: 1 }) },
  { additionalProperties: false },
);
export type Alias = Static<typeof AliasSchema>;
const OriginalSchema = Type.Object(
  {
    ref: OriginalRefSchema,
    source_session_id: Type.String({ minLength: 1 }),
    entry_id: Type.String({ minLength: 1 }),
    blob_hash: Type.String({ pattern: "^[a-f0-9]{64}$" }),
    media_type: Type.Literal("text/plain; charset=utf-8"),
    byte_length: integer(0),
  },
  { additionalProperties: false },
);
export const OriginalsSchema = Type.Object(
  {
    task_id: TaskIdSchema,
    bindings: Type.Array(OriginalSchema, { minItems: 1 }),
  },
  { additionalProperties: false },
);
export type Original = Static<typeof OriginalSchema>;
export interface MemoryItem {
  ref: string;
  resolved_ref?: string;
  source_task_id?: string;
  source_ref?: string;
  content: string;
  offset: number;
  total_chars: number | null;
  truncated: boolean;
  source_complete: boolean;
  range_complete: boolean;
  status: string;
  source_session_id?: string;
  entry_id?: string;
  tool_call_id?: string;
  tool_calls?: { id: string; name: string }[];
  is_error?: boolean;
  attachments?: { ref: string; part_index: number; media_type: string }[];
  error?: string;
}
