import type {
  ExtensionContext,
  SessionEntry,
} from "@earendil-works/pi-coding-agent";
import { Check } from "typebox/value";
import {
  REF_TYPE,
  SCOPE_TYPE,
  ReferencesSchema,
  ScopeSchema,
  type Binding,
  type References,
  SessionMemory,
} from "../pi/session-memory.ts";
import type { Task } from "../task/model.ts";
import { RESTART_TYPE, RestartSchema } from "../task/restart-model.ts";

export interface LocatedReference {
  ref: string;
  source_session_id: string;
  entry_id: string;
  tool_call_id?: string;
}
function records(entries: SessionEntry[]): References[] {
  return entries.flatMap((e) => {
    if (e.type !== "custom" || e.customType !== REF_TYPE) return [];
    if (!Check(ReferencesSchema, e.data))
      throw Error("CORRUPT_REFERENCE_METADATA");
    return [e.data];
  });
}
/** Old messages keep their ownership even when scope changes in the middle of a tool turn. */
export function messageOwners(
  entries: SessionEntry[],
): Map<string, string | null> {
  const known = new Map<string, string>();
  for (const row of records(entries))
    for (const b of row.bindings) known.set(b.entry_id, row.task_id);
  const result = new Map<string, string | null>();
  let task: string | null = null,
    assistantTask: string | null = null;
  for (const entry of entries) {
    if (entry.type === "custom" && entry.customType === RESTART_TYPE) {
      if (!Check(RestartSchema, entry.data)) throw Error("CORRUPT_RESTART_METADATA");
      task = null;
    }
    if (entry.type === "custom" && entry.customType === SCOPE_TYPE) {
      if (!Check(ScopeSchema, entry.data)) throw Error("CORRUPT_SESSION_SCOPE");
      task = entry.data.task_id;
    }
    if (entry.type !== "message") continue;
    if (entry.message.role === "user")
      result.set(entry.id, known.get(entry.id) ?? task);
    if (entry.message.role === "assistant") {
      assistantTask = known.get(entry.id) ?? task;
      result.set(entry.id, assistantTask);
    }
    if (entry.message.role === "toolResult")
      result.set(entry.id, known.get(entry.id) ?? assistantTask);
  }
  return result;
}
export async function loadReferences(
  task: Task,
  memory: SessionMemory,
): Promise<Map<string, LocatedReference>> {
  const sessions = new Map<
    string,
    Awaited<ReturnType<SessionMemory["files"]["readView"]>>
  >();
  for (const source of task.sessions)
    sessions.set(
      source.session_id,
      await memory.files.readView(source.file, source.session_id),
    );
  const result = new Map<string, LocatedReference>(),
    origins = new Map<string, string>();
  for (const view of sessions.values())
    for (const row of records(view.custom)) {
      if (row.task_id !== task.task_id) continue;
      const source = sessions.get(row.source_session_id);
      if (!source) throw Error("REFERENCE_SOURCE_NOT_REGISTERED");
      for (const binding of row.bindings) {
        if (!Number.isSafeInteger(Number(binding.ref.slice(1))))
          throw Error("CORRUPT_REFERENCE_COUNTER");
        const entry = source.byId.get(binding.entry_id);
        if (!entry || entry.type !== "message")
          throw Error(`REFERENCE_ENTRY_MISSING: ${binding.ref}`);
        const role = entry.message.role,
          prefix = binding.ref[0];
        if (
          (prefix === "U" && role !== "user") ||
          (prefix === "A" && role !== "assistant") ||
          (prefix === "T" &&
            (role !== "toolResult" ||
              !("tool_call_id" in binding) ||
              entry.message.toolCallId !== binding.tool_call_id))
        )
          throw Error("CORRUPT_REFERENCE_KIND");
        if (prefix === "T" && role === "toolResult") {
          const toolCallId = entry.message.toolCallId;
          let assistant = entry.parentId
            ? source.byId.get(entry.parentId)
            : undefined;
          while (
            assistant &&
            !(
              assistant.type === "message" &&
              assistant.message.role === "assistant"
            )
          ) {
            assistant = assistant.parentId
              ? source.byId.get(assistant.parentId)
              : undefined;
          }
          if (
            !assistant ||
            assistant.type !== "message" ||
            assistant.message.role !== "assistant" ||
            !assistant.message.content.some(
              (p) => p.type === "toolCall" && p.id === toolCallId,
            )
          )
            throw Error("UNPAIRED_TOOL_REFERENCE");
        }
        const locator = {
          ...binding,
          source_session_id: row.source_session_id,
        };
        const old = result.get(binding.ref),
          origin = `${row.source_session_id}:${binding.entry_id}`;
        if (old && JSON.stringify(old) !== JSON.stringify(locator))
          throw Error("REFERENCE_NUMBER_COLLISION");
        if (origins.has(origin) && origins.get(origin) !== binding.ref)
          throw Error("REFERENCE_ORIGIN_COLLISION");
        result.set(binding.ref, locator);
        origins.set(origin, binding.ref);
      }
    }
  return result;
}
/** Caller holds Task lock and has registered the current persistent Session. */
export async function synchronizeReferences(
  task: Task,
  ctx: ExtensionContext,
  memory: SessionMemory,
  bootstrap: Set<string> = new Set(),
): Promise<Map<string, LocatedReference>> {
  const references = await loadReferences(task, memory),
    entries = ctx.sessionManager.getBranch(),
    owners = messageOwners(entries);
  const known = new Set(
    [...references.values()].map((b) => `${b.source_session_id}:${b.entry_id}`),
  );
  const copied = new Set(
    records(entries)
      .filter((r) => r.task_id === task.task_id)
      .flatMap((r) => r.bindings.map((b) => b.entry_id)),
  );
  const next = { U: 0, A: 0, T: 0 };
  for (const ref of references.keys()) {
    const key = ref[0] as keyof typeof next;
    next[key] = Math.max(next[key], Number(ref.slice(1)));
  }
  const bindings: Binding[] = [];
  const current = ctx.sessionManager.getSessionId();
  for (const e of entries) {
    if (
      e.type !== "message" ||
      (owners.get(e.id) !== task.task_id && !bootstrap.has(e.id)) ||
      known.has(`${current}:${e.id}`) ||
      copied.has(e.id)
    )
      continue;
    const m = e.message;
    if (m.role === "user")
      bindings.push({ ref: `U${++next.U}`, entry_id: e.id });
    if (m.role === "assistant")
      bindings.push({ ref: `A${++next.A}`, entry_id: e.id });
    if (m.role === "toolResult")
      bindings.push({
        ref: `T${++next.T}`,
        entry_id: e.id,
        tool_call_id: m.toolCallId,
      });
  }
  if (Object.values(next).some((n) => !Number.isSafeInteger(n)))
    throw Error("REFERENCE_COUNTER_EXHAUSTED");
  if (bindings.length) {
    await memory.append(ctx, REF_TYPE, {
      task_id: task.task_id,
      source_session_id: current,
      bindings,
    });
    for (const b of bindings)
      references.set(b.ref, { ...b, source_session_id: current });
  }
  return references;
}
