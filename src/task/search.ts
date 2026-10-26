import { createHash } from "node:crypto";
import { stat } from "node:fs/promises";
import { Check } from "typebox/value";
import { Type } from "typebox";
import type { MemoryPaths } from "../storage/paths.ts";
import { atomicWrite, readOptional, withLock } from "../storage/files.ts";
import type { Task, FindInput } from "./model.ts";
import type { StateStore } from "../state/store.ts";
import {
  LocalEmbedding,
  type Embedder,
  type SearchSettings,
} from "./embedding.ts";
import { rankTasks } from "./search-rank.ts";
const RowSchema = Type.Object(
  {
    version: Type.Literal(1),
    checksum: Type.String(),
    model: Type.String(),
    stamp: Type.String(),
    fingerprint: Type.String(),
    goal: Type.String(),
    vector: Type.Array(Type.Number(), { minItems: 384, maxItems: 384 }),
    truncated: Type.Boolean(),
  },
  { additionalProperties: false },
);
type Row = {
  version: 1;
  checksum: string;
  model: string;
  stamp: string;
  fingerprint: string;
  goal: string;
  vector: number[];
  truncated: boolean;
};
const digest = (value: unknown) =>
  createHash("sha256").update(JSON.stringify(value)).digest("hex");
const checksum = (row: Row) =>
  digest({
    version: row.version,
    model: row.model,
    stamp: row.stamp,
    fingerprint: row.fingerprint,
    goal: row.goal,
    vector: row.vector,
    truncated: row.truncated,
  });
export interface SearchProgress {
  completed: number;
  total: number;
  indexed: number;
}
interface PreparedRow {
  task: Task;
  row: Row | undefined;
  stamp: string;
  fingerprint?: string;
  goal?: string;
  text?: string;
  write: boolean;
}
export class TaskSearch {
  readonly local: LocalEmbedding;
  readonly paths: MemoryPaths;
  readonly state: StateStore;
  readonly embed: Embedder;
  private rows = new Map<string, { row: Row; bytes: number }>();
  private bytes = 0;
  constructor(paths: MemoryPaths, state: StateStore, embed?: Embedder) {
    this.paths = paths;
    this.state = state;
    this.local = new LocalEmbedding(paths);
    this.embed = embed ?? this.local.embed;
  }
  close() {
    const stopped = this.local.dispose();
    this.rows.clear();
    this.bytes = 0;
    return stopped;
  }
  private remember(key: string, row: Row, limit: number) {
    const old = this.rows.get(key);
    if (old) {
      this.bytes -= old.bytes;
      this.rows.delete(key);
    }
    const bytes = Buffer.byteLength(JSON.stringify(row)) * 2 + 512;
    while (this.rows.size && this.bytes + bytes > limit) {
      const [k, v] = this.rows.entries().next().value!;
      this.bytes -= v.bytes;
      this.rows.delete(k);
    }
    if (bytes <= limit) {
      this.rows.set(key, { row, bytes });
      this.bytes += bytes;
    }
  }
  async find(
    tasks: Task[],
    input: FindInput,
    settings: SearchSettings,
    signal?: AbortSignal,
    onProgress?: (progress: SearchProgress) => void,
  ) {
    onProgress?.({ completed: 0, total: tasks.length, indexed: 0 });
    if (!tasks.length) return [];
    const query = await this.embed([input.query], "query", settings, signal);
    const queryVector = query.vectors[0]!;
    const docs = [];
    let indexed = 0;
    // Only communication is grouped: the worker still infers one text at a time.
    for (let offset = 0; offset < tasks.length; offset += 16) {
      signal?.throwIfAborted();
      const batch: PreparedRow[] = [];
      for (const task of tasks.slice(offset, offset + 16)) {
        signal?.throwIfAborted();
        const info = await stat(this.paths.state(task)),
          location = this.paths.search(task.task_id);
        const stamp = digest([
          info.dev,
          info.ino,
          info.size,
          info.mtimeMs,
          info.ctimeMs,
          task.title,
          task.project_name,
          task.summary,
          task.keywords,
        ]);
        let row = this.rows.get(task.task_id)?.row;
        if (!row) {
          try {
            const candidate: unknown = JSON.parse(
              (await readOptional(location.data)) ?? "null",
            );
            if (
              Check(RowSchema, candidate) &&
              candidate.checksum === checksum(candidate as Row)
            )
              row = candidate as Row;
          } catch {
            /* A derived index is disposable, never authoritative. */
          }
        }
        const model = settings.embedding.revision;
        const prepared: PreparedRow = { task, row, stamp, write: false };
        if (!row || row.stamp !== stamp || row.model !== model) {
          const state = await this.state.read(task),
            text = `Goal: ${state.goal}\nTitle: ${task.title}\nKeywords: ${task.keywords.join(", ")}\nProject: ${task.project_name}\nSummary: ${task.summary}`;
          const fingerprint = digest([model, text]);
          prepared.write = true;
          if (row?.fingerprint === fingerprint && row.model === model)
            prepared.row = { ...row, stamp };
          else {
            prepared.text = text;
            prepared.fingerprint = fingerprint;
            prepared.goal = state.goal;
          }
        }
        batch.push(prepared);
      }
      const changed = batch.filter((item) => item.text !== undefined);
      if (changed.length) {
        const output = await this.embed(
          changed.map((item) => item.text!), "passage", settings, signal,
        );
        signal?.throwIfAborted();
        if (output.vectors.length !== changed.length)
          throw Error("INVALID_TASK_EMBEDDING");
        for (const [i, item] of changed.entries()) {
          item.row = {
            version: 1,
            checksum: "",
            model: settings.embedding.revision,
            stamp: item.stamp,
            fingerprint: item.fingerprint!,
            goal: item.goal!,
            vector: output.vectors[i]!,
            truncated: output.truncated[i] ?? false,
          };
        }
        indexed += changed.length;
      }
      const writes = batch.filter((item) => item.write);
      // Validate the whole embedding reply before publishing any item from it.
      for (const { row: candidate, write } of batch) {
        const row = candidate!;
        if (!row || row.vector.length !== queryVector.length)
          throw Error("INVALID_TASK_EMBEDDING");
        if (write) {
          row.checksum = checksum(row);
          if (!Check(RowSchema, row) || !row.vector.every(Number.isFinite))
            throw Error("INVALID_TASK_EMBEDDING");
        }
      }
      for (let start = 0; start < writes.length; start += 4) {
        signal?.throwIfAborted();
        const settled = await Promise.allSettled(
          writes.slice(start, start + 4).map(({ task, row }) => {
            const location = this.paths.search(task.task_id);
            return withLock(
              location.lock,
              () => atomicWrite(location.data, JSON.stringify(row!) + "\n"),
              signal,
            );
          }),
        );
        for (const result of settled)
          if (result.status === "rejected") throw result.reason;
      }
      signal?.throwIfAborted();
      for (const { task, row: candidate } of batch) {
        const row = candidate!;
        this.remember(task.task_id, row, settings.cache_max_bytes);
        let dot = 0,
          a = 0,
          b = 0;
        for (let i = 0; i < row.vector.length; i++) {
          dot += row.vector[i]! * queryVector[i]!;
          a += row.vector[i]! ** 2;
          b += queryVector[i]! ** 2;
        }
        docs.push({
          ...task,
          goal: row.goal,
          vector: [],
          similarity: a && b ? dot / Math.sqrt(a * b) : 0,
          index_truncated: row.truncated,
        });
      }
      onProgress?.({
        completed: offset + batch.length, total: tasks.length, indexed,
      });
    }
    return rankTasks(
      docs,
      input.query,
      input.keywords ?? [],
      query.vectors[0]!,
      settings,
    )
      .slice(0, input.limit ?? settings.default_limit)
      .map((d) => ({
        task_id: d.task_id,
        title: d.title,
        summary: d.summary,
        keywords: d.keywords,
        goal: d.goal,
        workspace: d.workspace,
        score: d.score,
        ranks: d.ranks,
        index_truncated: d.index_truncated,
      }));
  }
}
