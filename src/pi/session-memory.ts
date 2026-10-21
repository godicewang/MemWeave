import { stat, open } from "node:fs/promises";
import { openSync, fsyncSync, closeSync } from "node:fs";
import { resolve } from "node:path";
import { Type, type Static } from "typebox";
import { Check } from "typebox/value";
import type {
  ExtensionAPI,
  ExtensionContext,
  SessionEntry,
} from "@earendil-works/pi-coding-agent";
import { CONFIG_SCHEMA } from "../config/schema.ts";
import { StateBatchSchema } from "../state/window.ts";
import { TaskIdSchema } from "../task/model.ts";
export const SCOPE_TYPE = "memweave.scope.v1",
  REF_TYPE = "memweave.references.v1";
export const STATE_REQUEST_TYPE = "memweave.state.request.v1";
export const ScopeSchema = Type.Object(
  {
    task_id: Type.Union([TaskIdSchema, Type.Null()]),
    overrides: Type.Partial(CONFIG_SCHEMA),
  },
  { additionalProperties: false },
);
export type Scope = Static<typeof ScopeSchema>;
const BindingSchema = Type.Union([
  Type.Object(
    {
      ref: Type.String({ pattern: "^[UA][1-9][0-9]*$" }),
      entry_id: Type.String({ minLength: 1 }),
    },
    { additionalProperties: false },
  ),
  Type.Object(
    {
      ref: Type.String({ pattern: "^T[1-9][0-9]*$" }),
      entry_id: Type.String({ minLength: 1 }),
      tool_call_id: Type.String({ minLength: 1 }),
    },
    { additionalProperties: false },
  ),
]);
export const ReferencesSchema = Type.Object(
  {
    task_id: TaskIdSchema,
    source_session_id: Type.String({ minLength: 1 }),
    bindings: Type.Array(BindingSchema, { minItems: 1 }),
  },
  { additionalProperties: false },
);
export type References = Static<typeof ReferencesSchema>;
export type Binding = References["bindings"][number];
export function workspaceKey(cwd: string): string {
  return `--${resolve(cwd)
    .replace(/^[/\\]/, "")
    .replace(/[/\\:]/g, "-")}--`;
}
export function scopeOf(entries: SessionEntry[]): Scope {
  let scope: Scope = { task_id: null, overrides: {} };
  for (const e of entries)
    if (e.type === "custom" && e.customType === SCOPE_TYPE) {
      if (!Check(ScopeSchema, e.data)) throw Error("CORRUPT_SESSION_SCOPE");
      scope = e.data;
    }
  return structuredClone(scope);
}
interface CachedSession {
  stamp: string;
  identity: string;
  size: number;
  sessionId: string;
  entries: SessionEntry[];
  byId: Map<string, SessionEntry>;
  custom: SessionEntry[];
}
/** Append-only native files are read from their last verified byte offset. Replacement/truncation reloads strictly. */
export class SessionFiles {
  readonly cache = new Map<string, CachedSession>();
  private readonly readers = new Map<string, Promise<void>>();
  async readView(file: string, sessionId: string): Promise<CachedSession> {
    const previous = this.readers.get(file);
    let release!: () => void;
    const current = new Promise<void>((resolve) => {
      release = resolve;
    });
    this.readers.set(file, current);
    await previous;
    try {
      return await this.readSerialized(file, sessionId);
    } finally {
      release();
      if (this.readers.get(file) === current) this.readers.delete(file);
    }
  }
  private async readSerialized(
    file: string,
    sessionId: string,
  ): Promise<CachedSession> {
    let info;
    try {
      info = await stat(file);
    } catch {
      throw Error(`REFERENCE_SOURCE_MISSING: ${sessionId}`);
    }
    const identity = `${info.dev}:${info.ino}`,
      stamp = `${identity}:${info.size}:${info.mtimeMs}:${info.ctimeMs}`;
    const cached = this.cache.get(file);
    if (cached?.stamp === stamp && cached.sessionId === sessionId)
      return cached;
    const incremental =
      cached?.identity === identity &&
      cached.sessionId === sessionId &&
      info.size > cached.size;
    const offset = incremental ? cached.size : 0;
    let rows: unknown[];
    try {
      const fd = await open(file, "r");
      const bytes = Buffer.alloc(info.size - offset);
      try {
        let read = 0;
        while (read < bytes.length) {
          const result = await fd.read(
            bytes,
            read,
            bytes.length - read,
            offset + read,
          );
          if (!result.bytesRead) throw Error();
          read += result.bytesRead;
        }
      } finally {
        await fd.close();
      }
      const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      if (!text.endsWith("\n")) throw Error();
      rows = text
        .trimEnd()
        .split("\n")
        .map((line) => JSON.parse(line) as unknown);
    } catch {
      throw Error(`CORRUPT_REFERENCE_SOURCE: ${sessionId}`);
    }
    if (!incremental) {
      const header = rows.shift() as
        | { type?: unknown; id?: unknown; version?: unknown }
        | undefined;
      if (
        header?.type !== "session" ||
        header.id !== sessionId ||
        header.version !== 3
      )
        throw Error(`UNSUPPORTED_REFERENCE_SESSION: ${sessionId}`);
    }
    const view: CachedSession = incremental
      ? { ...cached, stamp, size: info.size }
      : {
          stamp,
          identity,
          size: info.size,
          sessionId,
          entries: [],
          byId: new Map(),
          custom: [],
        };
    const stagedIds = new Set<string>();
    for (const row of rows) {
      const e = row as Partial<SessionEntry>;
      if (
        !e ||
        typeof e.type !== "string" ||
        typeof e.id !== "string" ||
        view.byId.has(e.id) ||
        stagedIds.has(e.id) ||
        typeof e.timestamp !== "string" ||
        (e.parentId !== null &&
          (typeof e.parentId !== "string" ||
            (!view.byId.has(e.parentId) && !stagedIds.has(e.parentId))))
      )
        throw Error(`CORRUPT_REFERENCE_SOURCE: ${sessionId}`);
      if (
        e.type === "message" &&
        (!e.message || typeof e.message.role !== "string")
      )
        throw Error(`CORRUPT_REFERENCE_SOURCE: ${sessionId}`);
      stagedIds.add(e.id);
    }
    for (const row of rows) {
      const e = row as SessionEntry;
      view.byId.set(e.id, e);
      view.entries.push(e);
      if (e.type === "custom") view.custom.push(e);
    }
    this.cache.set(file, view);
    return view;
  }
  async read(file: string, sessionId: string): Promise<SessionEntry[]> {
    return (await this.readView(file, sessionId)).entries;
  }
}
export class SessionMemory {
  readonly pi: Pick<ExtensionAPI, "appendEntry">;
  readonly files = new SessionFiles();
  failed = false;
  constructor(pi: Pick<ExtensionAPI, "appendEntry">) {
    this.pi = pi;
  }
  check(): void {
    if (this.failed)
      throw Error(
        "SESSION_WRITE_FAILED: reload the Session from disk before continuing",
      );
  }
  async verify(ctx: ExtensionContext): Promise<void> {
    this.check();
    const own = ctx.sessionManager
      .getBranch()
      .filter(
        (e) =>
          e.type === "custom" &&
          (e.customType === SCOPE_TYPE ||
            e.customType === REF_TYPE ||
            e.customType === STATE_REQUEST_TYPE),
      );
    if (!own.length) return;
    const file = ctx.sessionManager.getSessionFile();
    if (!file) throw Error("PERSISTENT_SESSION_REQUIRED");
    const view = await this.files.readView(
      file,
      ctx.sessionManager.getSessionId(),
    );
    for (const entry of own)
      if (JSON.stringify(view.byId.get(entry.id)) !== JSON.stringify(entry)) {
        this.failed = true;
        ctx.abort();
        throw Error(
          "SESSION_STATE_DIVERGED: own metadata is not durable; reopen Session from disk",
        );
      }
  }
  async append(
    ctx: ExtensionContext,
    kind: string,
    data: unknown,
  ): Promise<void> {
    if (
      (kind === SCOPE_TYPE && !Check(ScopeSchema, data)) ||
      (kind === REF_TYPE && !Check(ReferencesSchema, data)) ||
      (kind === STATE_REQUEST_TYPE && !Check(StateBatchSchema, data))
    )
      throw Error("INVALID_SESSION_METADATA");
    await this.verify(ctx);
    const file = ctx.sessionManager.getSessionFile();
    if (!file) throw Error("PERSISTENT_SESSION_REQUIRED");
    try {
      this.pi.appendEntry(kind, data);
      const leaf = ctx.sessionManager.getLeafEntry();
      if (!leaf) throw Error();
      const entries = await this.files.read(
        file,
        ctx.sessionManager.getSessionId(),
      );
      const saved = entries.find((e) => e.id === leaf.id);
      if (!saved || JSON.stringify(saved) !== JSON.stringify(leaf))
        throw Error();
      const fd = openSync(file, "r");
      try {
        fsyncSync(fd);
      } finally {
        closeSync(fd);
      }
    } catch {
      this.failed = true;
      ctx.abort();
      throw Error(
        "SESSION_WRITE_FAILED: metadata durability unconfirmed; reload from disk",
      );
    }
  }
}
export function sourceAssistant(ctx: ExtensionContext, callId: string) {
  const entries = ctx.sessionManager.getBranch();
  for (let i = entries.length - 1; i >= 0; i--) {
    const e = entries[i]!;
    if (
      e.type === "message" &&
      e.message.role === "assistant" &&
      e.message.content.some((p) => p.type === "toolCall" && p.id === callId)
    )
      return e;
  }
  throw Error("TOOL_SOURCE_MISSING: native assistant entry required");
}
