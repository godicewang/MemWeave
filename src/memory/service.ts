import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import type { ImageContent } from "@earendil-works/pi-ai";
import { Check } from "typebox/value";
import type { Task } from "../task/model.ts";
import type { TaskIndex } from "../task/index-store.ts";
import type { SessionMemory } from "../pi/session-memory.ts";
import type { LocatedReference } from "./references.ts";
import { originalSource } from "../pi/original-source.ts";
import { originalImage } from "../pi/original-image.ts";
import { BlobStore } from "../storage/blobs.ts";
import type { MemoryPaths } from "../storage/paths.ts";
import {
  ALIAS_TYPE,
  ORIGINAL_TYPE,
  MemoryReadSchema,
  type MemoryReadInput,
  type MemoryItem,
  type Alias,
  type Original,
} from "./model.ts";
import { aliasOrigin, loadAliases, loadOriginals } from "./metadata.ts";
import { normalizeMessage, textRange } from "./text.ts";
import type { NativeMessage } from "../window/select.ts";

export interface MemoryReadOutput {
  result: { items: MemoryItem[]; total_chars: number };
  images: ImageContent[];
}
export class MemoryService {
  readonly blobs: BlobStore;
  readonly index: TaskIndex;
  readonly memory: SessionMemory;
  private readonly inspected = new Set<string>();
  constructor(paths: MemoryPaths, index: TaskIndex, memory: SessionMemory) {
    this.blobs = new BlobStore(paths);
    this.index = index;
    this.memory = memory;
  }

  /** Caller holds the Task lock. Never interprets a path mentioned in ordinary text. */
  async capture(
    task: Task,
    refs: Map<string, LocatedReference>,
    ctx: ExtensionContext,
  ) {
    const originals = await loadOriginals(task, this.memory),
      additions: Original[] = [];
    for (const [ref, location] of refs) {
      const key = `${task.task_id}:${ref}`;
      if (ref[0] !== "T" || originals.has(ref) || this.inspected.has(key))
        continue;
      const source = task.sessions.find(
        (s) => s.session_id === location.source_session_id,
      );
      if (!source) throw Error("REFERENCE_SOURCE_NOT_REGISTERED");
      const entry = (
        await this.memory.files.readView(source.file, source.session_id)
      ).byId.get(location.entry_id);
      if (entry?.type !== "message" || entry.message.role !== "toolResult")
        throw Error("REFERENCE_ENTRY_MISSING");
      const message = entry.message,
        details = message.details as { fullOutputPath?: unknown } | undefined;
      if (
        message.toolName !== "bash" ||
        typeof details?.fullOutputPath !== "string"
      ) {
        this.inspected.add(key);
        continue;
      }
      ctx.signal?.throwIfAborted();
      let blob;
      try {
        blob = await this.blobs.save(details.fullOutputPath);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "ENOENT") continue;
        throw Error(`ORIGINAL_SAVE_FAILED: ${task.task_id}/${ref}`);
      }
      additions.push({
        ref,
        source_session_id: location.source_session_id,
        entry_id: location.entry_id,
        ...blob,
        media_type: "text/plain; charset=utf-8",
      });
    }
    if (additions.length)
      await this.memory.append(ctx, ORIGINAL_TYPE, {
        task_id: task.task_id,
        bindings: additions,
      });
  }

  private async source(alias: Omit<Alias, "ref">) {
    const task = await this.index.get(alias.source_task_id),
      source = await originalSource(task, alias.source_ref, this.memory);
    return { task, ...source };
  }
  /** Caller holds the current Task lock; uses the existing alias contract, never a Window map. */
  async attachmentRefs(
    task: Task,
    sourceTask: string,
    sourceRef: string,
    message: NativeMessage,
    ctx: ExtensionContext,
  ) {
    const aliases = await loadAliases(task, this.memory),
      result: { ref: string }[] = [];
    if (!Array.isArray(message.content)) return result;
    for (const [index, part] of message.content.entries())
      if (part.type === "image")
        result.push({
          ref: await this.allocateAlias(
            task,
            {
              source_task_id: sourceTask,
              source_ref: sourceRef,
              part_index: index,
            },
            ctx,
            aliases,
          ),
        });
    return result;
  }
  private async allocateAlias(
    task: Task,
    origin: Omit<Alias, "ref">,
    ctx: ExtensionContext,
    aliases: Map<string, Alias>,
  ) {
    const existing = [...aliases.values()].find(
      (alias) => aliasOrigin(alias) === aliasOrigin(origin),
    );
    if (existing) return existing.ref;
    let next = 1;
    for (const ref of aliases.keys())
      next = Math.max(next, Number(ref.slice(1)) + 1);
    if (!Number.isSafeInteger(next)) throw Error("ALIAS_COUNTER_EXHAUSTED");
    const alias = { ...origin, ref: `R${next}` };
    await this.memory.append(ctx, ALIAS_TYPE, {
      task_id: task.task_id,
      bindings: [alias],
    });
    aliases.set(alias.ref, alias);
    return alias.ref;
  }
  async evidence(task: Task, requested: Iterable<string>): Promise<string[]> {
    const refs = [...new Set(requested)].filter((ref) => ref.startsWith("R"));
    if (!refs.length) return [];
    const aliases = await loadAliases(task, this.memory);
    for (const ref of refs) {
      const alias = aliases.get(ref);
      if (!alias) throw Error(`INVALID_EVIDENCE: ${ref} is not registered`);
      try {
        const source = await this.source(alias);
        if (alias.part_index !== undefined) {
          const content = source.message.content;
          if (!Array.isArray(content)) throw Error();
          // Evidence existence is independent of this request's image presentation budget.
          originalImage(content[alias.part_index], Number.MAX_SAFE_INTEGER);
        }
      } catch {
        throw Error(`INVALID_EVIDENCE: ${ref} source is unavailable`);
      }
    }
    return refs;
  }
  async read(
    task: Task,
    input: MemoryReadInput,
    ctx: ExtensionContext,
  ): Promise<MemoryReadOutput> {
    if (!Check(MemoryReadSchema, input)) throw Error("INVALID_MEMORY_READ");
    const aliases = await loadAliases(task, this.memory),
      images: ImageContent[] = [],
      items: MemoryItem[] = [];
    let remaining = input.max_total_chars ?? 8000,
      imageBytes = 0;
    const aliasFor = (origin: Omit<Alias, "ref">) =>
      this.allocateAlias(task, origin, ctx, aliases);
    for (const request of input.items) {
      ctx.signal?.throwIfAborted();
      const item: MemoryItem = {
        ref: request.ref,
        content: "",
        offset: request.offset ?? 0,
        total_chars: null,
        truncated: true,
        source_complete: false,
        range_complete: false,
        status: "read_error",
      };
      items.push(item);
      try {
        if (
          request.ref.startsWith("R") &&
          request.task_id &&
          request.task_id !== task.task_id
        )
          throw Error("CROSS_TASK_R_NOT_ALLOWED");
        const alias = request.ref.startsWith("R")
          ? aliases.get(request.ref)
          : {
              source_task_id: request.task_id ?? task.task_id,
              source_ref: request.ref,
            };
        if (!alias) throw Error("REFERENCE_NOT_FOUND");
        Object.assign(item, {
          source_task_id: alias.source_task_id,
          source_ref: alias.source_ref,
        });
        const source = await this.source(alias);
        Object.assign(item, {
          source_task_id: alias.source_task_id,
          source_ref: alias.source_ref,
          ...source.location,
          ref: request.ref,
        });
        const content = source.message.content;
        if ("part_index" in alias && alias.part_index !== undefined) {
          if (request.offset !== undefined || request.limit !== undefined)
            throw Error("INVALID_IMAGE_RANGE");
          if (!ctx.model?.input.includes("image"))
            throw Error("MODEL_IMAGE_UNSUPPORTED");
          if (!Array.isArray(content))
            throw Error("UNSUPPORTED_ORIGINAL_MEDIA");
          const original = originalImage(
            content[alias.part_index],
            10 * 1024 * 1024 - imageBytes,
          );
          if (imageBytes + original.bytes > 10 * 1024 * 1024)
            throw Error("IMAGE_BUDGET_EXCEEDED");
          images.push(original.image);
          imageBytes += original.bytes;
          Object.assign(item, {
            resolved_ref: request.ref,
            source_complete: true,
            range_complete: true,
            truncated: false,
            status: "ok",
            total_chars: 0,
          });
          continue;
        }
        const normalized = normalizeMessage(source.message),
          original = (await loadOriginals(source.task, this.memory)).get(
            alias.source_ref,
          );
        if (
          original &&
          (original.entry_id !== source.location.entry_id ||
            original.source_session_id !== source.location.source_session_id)
        )
          throw Error("ORIGINAL_SOURCE_MISMATCH");
        let range;
        const limit = request.limit ?? Number.MAX_SAFE_INTEGER;
        if (original)
          range = await this.blobs.text(
            original,
            item.offset,
            limit,
            remaining,
          );
        else range = textRange(normalized.text, item.offset, limit, remaining);
        const complete = original ? true : normalized.source_complete;
        Object.assign(item, range, {
          source_complete: complete,
          total_chars: complete ? range.total_chars : null,
          range_complete: complete && range.range_complete,
          truncated: range.truncated || !complete,
          status: !normalized.supported
            ? "unsupported_media"
            : !range.range_complete && !remaining
              ? "budget_exhausted"
              : complete
                ? "ok"
                : "incomplete",
        });
        if (!complete)
          item.error =
            "ORIGINAL_INCOMPLETE: only the recorded text fragment is available; full-original character positions are unknown";
        if (source.message.role === "toolResult")
          item.is_error = source.message.isError;
        if (normalized.tool_calls.length)
          item.tool_calls = normalized.tool_calls;
        item.resolved_ref =
          alias.source_task_id === task.task_id
            ? request.ref
            : await aliasFor(alias);
        if (normalized.attachments.length) {
          item.attachments = [];
          for (const attachment of normalized.attachments)
            item.attachments.push({
              ...attachment,
              ref: await aliasFor({
                source_task_id: alias.source_task_id,
                source_ref: alias.source_ref,
                part_index: attachment.part_index,
              }),
            });
        }
        remaining -= [...range.content].length;
      } catch (error) {
        if (this.memory.failed || ctx.signal?.aborted) throw error;
        const message =
          error instanceof Error ? error.message : "ORIGINAL_READ_FAILED";
        item.content = "";
        item.total_chars = null;
        item.source_complete = false;
        item.range_complete = false;
        item.truncated = true;
        item.status = /NOT_FOUND/.test(message)
          ? "not_found"
          : /MISSING|ENOENT/.test(message)
            ? "source_missing"
            : /MODEL_IMAGE_UNSUPPORTED/.test(message)
              ? "model_unsupported"
              : /IMAGE_BUDGET/.test(message)
                ? "image_budget_exceeded"
                : /UNSUPPORTED.*MEDIA/.test(message)
                  ? "unsupported_media"
                  : "read_error";
        item.error = message;
      }
    }
    return {
      result: {
        items,
        total_chars: (input.max_total_chars ?? 8000) - remaining,
      },
      images,
    };
  }
}
