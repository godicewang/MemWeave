import { Type, type Static } from "typebox";
import { Check } from "typebox/value";
import { isDeepStrictEqual } from "node:util";
import {
  SessionManager,
  type ExtensionContext,
  type SessionEntry,
} from "@earendil-works/pi-coding-agent";
import type { Task, ResumeInput } from "./model.ts";
import { ResumeSchema, TaskIdSchema } from "./model.ts";
import type { TaskService } from "./service.ts";
import { messageOwners } from "../memory/references.ts";
import { indexEvents, type InteractionEvent } from "../window/select.ts";
import type { MemoryConfig } from "../config/schema.ts";
import {
  REF_TYPE,
  ReferencesSchema,
  sourceAssistant,
  SCOPE_TYPE,
} from "../pi/session-memory.ts";
import { restartMetadata } from "./restart-model.ts";
export const RESUME_TYPE = "memweave.resume.v1";
const id = Type.String({ minLength: 1 }),
  integer = Type.Integer({ minimum: 1, maximum: Number.MAX_SAFE_INTEGER });
export const ResumeWindowSchema = Type.Object(
  {
    task_id: TaskIdSchema,
    source_session_id: id,
    source_anchor_entry_id: id,
    seed_event_ids: Type.Array(id, { uniqueItems: true }),
    target_anchor_entry_id: Type.Union([id, Type.Null()]),
    recent_turns: integer,
    evict_turns: integer,
  },
  { additionalProperties: false },
);
export type ResumeWindow = Static<typeof ResumeWindowSchema>;
export interface ResumeRecord {
  id: string;
  position: number;
  data: ResumeWindow;
}
export function resumeMetadata(entries: SessionEntry[]): ResumeRecord | null {
  for (let position = entries.length - 1; position >= 0; position--) {
    const e = entries[position]!;
    if (e.type !== "custom" || e.customType !== RESUME_TYPE) continue;
    if (
      !Check(ResumeWindowSchema, e.data) ||
      e.data.evict_turns > e.data.recent_turns ||
      e.data.seed_event_ids.length > e.data.recent_turns
    )
      throw Error("CORRUPT_RESUME_METADATA");
    return { id: e.id, position, data: e.data };
  }
  return null;
}
function frozenBranch(entries: SessionEntry[], anchor: string) {
  const byId = new Map(entries.map((e) => [e.id, e])),
    branch: SessionEntry[] = [],
    seen = new Set<string>();
  let current = byId.get(anchor);
  if (!current) throw Error("RESUME_SOURCE_ANCHOR_MISSING");
  while (current) {
    if (seen.has(current.id)) throw Error("CORRUPT_RESUME_SOURCE");
    seen.add(current.id);
    branch.push(current);
    if (current.parentId === null) break;
    current = byId.get(current.parentId);
    if (!current) throw Error("CORRUPT_RESUME_SOURCE");
  }
  return branch.reverse();
}
function ownedEvents(entries: SessionEntry[], taskId: string) {
  const owners = messageOwners(entries);
  return indexEvents(entries).filter((event) =>
    event.messages.every((item) => owners.get(item.entryId) === taskId),
  );
}
export function receiptForCall(
  entries: SessionEntry[],
  assistantId: string,
  taskId?: string,
) {
  const start = entries.findIndex((e) => e.id === assistantId);
  if (start < 0) throw Error("TOOL_SOURCE_MISSING");
  for (let i = start + 1; i < entries.length; i++) {
    const e = entries[i]!;
    if (e.type === "message" && e.message.role !== "toolResult") break;
    if (e.type === "custom" && e.customType === RESUME_TYPE) {
      const record = resumeMetadata(entries.slice(0, i + 1))!;
      if (taskId !== undefined && record.data.task_id !== taskId)
        throw Error("RESUME_OPERATION_MISMATCH");
      return record;
    }
  }
  return null;
}
export async function prepareResume(
  tasks: TaskService,
  task: Task,
  ctx: ExtensionContext,
  callId: string,
  config: MemoryConfig,
): Promise<ResumeWindow> {
  const actual = ctx.sessionManager.getBranch(),
    assistant = sourceAssistant(ctx, callId),
    old = receiptForCall(actual, assistant.id, task.task_id);
  if (old) return old.data;
  const origin = ctx.sessionManager.getBranch(assistant.id),
    trigger = origin.findLast(
      (e) => e.type === "message" && e.message.role === "user",
    );
  if (!trigger) throw Error("RESUME_INPUT_REQUIRED");
  const triggerPosition = actual.findIndex((e) => e.id === trigger.id),
    prefix = actual.slice(0, triggerPosition);
  const targetAnchor = prefix.at(-1)?.id ?? null;
  const choices: {
    session: string;
    anchor: string;
    events: InteractionEvent[];
    time: number;
    order: number;
  }[] = [];
  for (const [order, source] of task.sessions.entries()) {
    const view = await tasks.memory.files.readView(
      source.file,
      source.session_id,
    );
    const branch =
      source.session_id === ctx.sessionManager.getSessionId()
        ? prefix
        : SessionManager.open(source.file).getBranch();
    if (
      branch.some(
        (e) => JSON.stringify(e) !== JSON.stringify(view.byId.get(e.id)),
      )
    )
      throw Error("RESUME_SOURCE_CHANGED");
    const events = ownedEvents(branch, task.task_id);
    if (!events.length) continue;
    // Native edits/compaction may hide or replace raw events. Never substitute a summary.
    if (
      branch.some((e) => e.type === "context_edit" || e.type === "compaction")
    ) {
      const projection = SessionManager.open(
        source.file,
      ).buildSessionProjection();
      if (
        events
          .slice(-config.recent_turns)
          .some((event) =>
            event.messages.some(
              (item) =>
                !projection.entries.some((e) =>
                  e.messages.some((m) => isDeepStrictEqual(m, item.message)),
                ),
            ),
          )
      )
        throw Error("UNSUPPORTED_RESUME_PROJECTION");
    }
    const last = events.at(-1)!,
      entry = branch.find((e) => e.id === last.id)!;
    choices.push({
      session: source.session_id,
      anchor: branch.at(-1)!.id,
      events,
      time: Date.parse(entry.timestamp),
      order,
    });
  }
  const chosen = choices.sort(
    (a, b) => b.time - a.time || b.order - a.order,
  )[0];
  if (!chosen)
    throw Error("RESUME_SOURCE_MISSING: no registered complete Task events");
  return {
    task_id: task.task_id,
    source_session_id: chosen.session,
    source_anchor_entry_id: chosen.anchor,
    seed_event_ids: chosen.events.slice(-config.recent_turns).map((e) => e.id),
    target_anchor_entry_id: targetAnchor,
    recent_turns: config.recent_turns,
    evict_turns: config.evict_turns,
  };
}
export function resumeCommitted(entries: SessionEntry[], record: ResumeRecord) {
  for (const e of entries.slice(record.position + 1)) {
    if (
      e.type === "custom" &&
      e.customType === SCOPE_TYPE &&
      typeof e.data === "object" &&
      e.data !== null &&
      "task_id" in e.data &&
      e.data.task_id === record.data.task_id
    )
      return true;
  }
  return false;
}
export function resumeSourceCall(
  entries: SessionEntry[],
  record: ResumeRecord,
): { callId: string; input: ResumeInput } {
  const assistant = entries
    .slice(0, record.position)
    .findLast((e) => e.type === "message" && e.message.role === "assistant");
  if (assistant?.type !== "message" || assistant.message.role !== "assistant")
    throw Error("RESUME_OPERATION_MISSING");
  const before = entries.slice(0, entries.indexOf(assistant));
  const trigger = before.findLast(
    (e) => e.type === "message" && e.message.role === "user",
  );
  if (
    !trigger ||
    (before.slice(0, before.indexOf(trigger)).at(-1)?.id ?? null) !==
      record.data.target_anchor_entry_id
  )
    throw Error("RESUME_TARGET_ANCHOR_MISMATCH");
  const calls = assistant.message.content.filter(
    (p) => p.type === "toolCall" && p.name === "task_resume",
  );
  if (
    calls.length !== 1 ||
    calls[0]?.type !== "toolCall" ||
    !Check(ResumeSchema, calls[0].arguments)
  )
    throw Error("RESUME_OPERATION_MISMATCH");
  const input = calls[0].arguments;
  if ("task_id" in input && input.task_id !== record.data.task_id)
    throw Error("RESUME_OPERATION_MISMATCH");
  return { callId: calls[0].id, input };
}
/** Build a disposable view with qualified foreign IDs; native files/messages are never rewritten. */
export async function resumedHistory(
  tasks: TaskService,
  ctx: ExtensionContext,
  config: Pick<MemoryConfig, "recent_turns" | "evict_turns">,
  actual = ctx.sessionManager.getBranch(),
) {
  const receipt = resumeMetadata(actual),
    restart = restartMetadata(actual);
  if (!receipt || (restart && restart.position > receipt.position))
    return { entries: actual, ageEntries: actual, events: undefined };
  resumeSourceCall(actual, receipt);
  const data = receipt.data,
    task = await tasks.index.get(data.task_id),
    registration = task.sessions.find(
      (s) => s.session_id === data.source_session_id,
    );
  if (!registration) throw Error("RESUME_SOURCE_NOT_REGISTERED");
  const view = await tasks.memory.files.readView(
      registration.file,
      registration.session_id,
    ),
    branch = frozenBranch(view.entries, data.source_anchor_entry_id),
    owned = ownedEvents(branch, data.task_id);
  if (
    !isDeepStrictEqual(
      owned.slice(-data.recent_turns).map((e) => e.id),
      data.seed_event_ids,
    )
  )
    throw Error("RESUME_SEED_CHANGED");
  const foreign = data.source_session_id !== ctx.sessionManager.getSessionId(),
    key = (id: string) => (foreign ? `${data.source_session_id}:${id}` : id);
  const seed = owned
    .slice(-config.recent_turns)
    .map((e) => ({
      id: key(e.id),
      messages: e.messages.map((m) => ({ ...m, entryId: key(m.entryId) })),
    }));
  const anchor =
    data.target_anchor_entry_id === null
      ? -1
      : actual.findIndex((e) => e.id === data.target_anchor_entry_id);
  if (data.target_anchor_entry_id !== null && anchor < 0)
    throw Error("RESUME_TARGET_ANCHOR_MISSING");
  const after = actual.slice(anchor + 1),
    seen = new Set(seed.map((e) => e.id));
  const events = [
    ...seed,
    ...indexEvents(after).filter((e) => !seen.has(e.id)),
  ];
  const prefix: SessionEntry[] = foreign
    ? branch.flatMap<SessionEntry>((e) => {
        if (e.type === "message") return [{ ...e, id: key(e.id) }];
        if (e.type === "custom" && e.customType === REF_TYPE) {
          if (!Check(ReferencesSchema, e.data))
            throw Error("CORRUPT_REFERENCE_METADATA");
          return [
            {
              ...e,
              id: key(e.id),
              data: {
                ...e.data,
                bindings: e.data.bindings.map((b) => ({
                  ...b,
                  entry_id: key(b.entry_id),
                })),
              },
            },
          ];
        }
        return [];
      })
    : [];
  return {
    entries: [...prefix, ...actual],
    ageEntries: foreign ? [...prefix, ...after] : actual,
    events,
  };
}
