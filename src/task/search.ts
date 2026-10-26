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
    this.local.dispose();
    this.rows.clear();
    this.bytes = 0;
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
  ) {
    if (!tasks.length) return [];
    const query = await this.embed([input.query], "query", settings, signal);
    const queryVector = query.vectors[0]!;
    const docs = [];
    for (const task of tasks) {
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
      if (!row || row.stamp !== stamp || row.model !== model) {
        const state = await this.state.read(task),
          text = `Goal: ${state.goal}\nTitle: ${task.title}\nKeywords: ${task.keywords.join(", ")}\nProject: ${task.project_name}\nSummary: ${task.summary}`;
        const fingerprint = digest([model, text]);
        if (row?.fingerprint === fingerprint && row.model === model)
          row = { ...row, stamp };
        else {
          const output = await this.embed([text], "passage", settings, signal);
          row = {
            version: 1,
            checksum: "",
            model,
            stamp,
            fingerprint,
            goal: state.goal,
            vector: output.vectors[0]!,
            truncated: output.truncated[0] ?? false,
          };
        }
        row.checksum = checksum(row);
        if (!Check(RowSchema, row) || !row.vector.every(Number.isFinite))
          throw Error("INVALID_TASK_EMBEDDING");
        const next = row;
        await withLock(
          location.lock,
          () => atomicWrite(location.data, JSON.stringify(next) + "\n"),
          signal,
        );
      }
      this.remember(task.task_id, row, settings.cache_max_bytes);
      if (row.vector.length !== queryVector.length)
        throw Error("INVALID_TASK_EMBEDDING");
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
