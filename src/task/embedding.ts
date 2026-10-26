import { Worker } from "node:worker_threads";
import { readFile, stat } from "node:fs/promises";
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { atomicWrite, withLock } from "../storage/files.ts";
import type { MemoryPaths } from "../storage/paths.ts";
import type { PolicySettings } from "../config/defaults.ts";
export type SearchSettings = PolicySettings["task_search"];
export interface EmbeddingResult {
  vectors: number[][];
  truncated: boolean[];
}
export type Embedder = (
  texts: string[],
  kind: "query" | "passage",
  settings: SearchSettings,
  signal?: AbortSignal,
) => Promise<EmbeddingResult>;
interface ModelManifest {
  model: string;
  revision: string;
  dimensions: number;
  max_tokens: number;
  files: { file: string; size: number; sha256: string }[];
}
async function fileHash(file: string) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return hash.digest("hex");
}
export async function ensureEmbeddingModel(
  paths: MemoryPaths,
  settings: SearchSettings,
  signal?: AbortSignal,
) {
  const manifest = JSON.parse(
    await readFile(
      new URL("../../resources/embedding/e5-small.json", import.meta.url),
      "utf8",
    ),
  ) as ModelManifest;
  if (
    settings.embedding.model !== manifest.model ||
    settings.embedding.revision !== manifest.revision
  )
    throw Error("UNSUPPORTED_TASK_EMBEDDING_MODEL");
  await withLock(
    paths.modelLock,
    async () => {
      for (const resource of manifest.files) {
        signal?.throwIfAborted();
        const file = paths.modelFile(resource.file);
        let valid = false;
        try {
          if ((await stat(file)).size === resource.size)
            valid = (await fileHash(file)) === resource.sha256;
        } catch {
          /* Rebuild only disposable model resources. */
        }
        if (valid) continue;
        const timeout = AbortSignal.timeout(settings.model_timeout_ms);
        const response = await fetch(
          `https://huggingface.co/${manifest.model}/resolve/${manifest.revision}/${resource.file}`,
          { signal: signal ? AbortSignal.any([signal, timeout]) : timeout },
        );
        if (!response.ok)
          throw Error(
            `TASK_MODEL_DOWNLOAD_FAILED: ${resource.file} HTTP ${response.status}`,
          );
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (
          bytes.byteLength !== resource.size ||
          createHash("sha256").update(bytes).digest("hex") !== resource.sha256
        )
          throw Error(`TASK_MODEL_CHECKSUM_FAILED: ${resource.file}`);
        await atomicWrite(file, bytes);
      }
    },
    signal,
  );
  return manifest;
}
/** One lazy CPU worker per runtime. No query vectors or input text survive completed calls. */
export class LocalEmbedding {
  private worker: Worker | undefined;
  private idle: ReturnType<typeof setTimeout> | undefined;
  private queue: Promise<unknown> = Promise.resolve();
  private prepared = false;
  private disposed = false;
  private stopping: Promise<void> = Promise.resolve();
  private sequence = 0;
  private pending = new Map<
    number,
    {
      resolve: (value: EmbeddingResult) => void;
      reject: (error: Error) => void;
    }
  >();
  readonly paths: MemoryPaths;
  constructor(paths: MemoryPaths) {
    this.paths = paths;
  }
  readonly embed: Embedder = (texts, kind, settings, signal) => {
    const operation = this.queue.then(() =>
      this.run(texts, kind, settings, signal),
    );
    this.queue = operation.then(
      () => undefined,
      () => undefined,
    );
    return operation;
  };
  dispose(): void {
    this.disposed = true;
    this.close();
  }
  close(): void {
    if (this.idle) clearTimeout(this.idle);
    this.idle = undefined;
    const worker = this.worker;
    this.worker = undefined;
    this.prepared = false;
    for (const job of this.pending.values())
      job.reject(Error("TASK_EMBEDDING_STOPPED"));
    this.pending.clear();
    if (worker) {
      // Let ORT release native allocations before the isolate goes away. A failed
      // worker must still be bounded, and a replacement waits for this exit.
      this.stopping = new Promise((resolve) => {
        const timer = setTimeout(() => {
          void worker.terminate();
        }, 5000);
        timer.unref();
        worker.once("exit", () => {
          clearTimeout(timer);
          resolve();
        });
        worker.unref();
        worker.postMessage({ close: true });
      });
    }
  }
  private async run(
    texts: string[],
    kind: "query" | "passage",
    settings: SearchSettings,
    signal?: AbortSignal,
  ): Promise<EmbeddingResult> {
    if (this.disposed) throw Error("TASK_EMBEDDING_STOPPED");
    await this.stopping;
    if (this.disposed) throw Error("TASK_EMBEDDING_STOPPED");
    signal?.throwIfAborted();
    if (this.idle) clearTimeout(this.idle);
    if (!this.prepared) {
      await ensureEmbeddingModel(this.paths, settings, signal);
      this.prepared = true;
    }
    if (!this.worker) {
      const worker = new Worker(
        new URL("./embedding-worker.ts", import.meta.url),
        {
          workerData: {
            model: this.paths.modelFile("onnx/model_quantized.onnx"),
            tokenizer: this.paths.modelFile("tokenizer.json"),
            tokenizerConfig: this.paths.modelFile("tokenizer_config.json"),
          },
          execArgv: [],
          resourceLimits: { maxOldGenerationSizeMb: 256 },
        },
      );
      this.worker = worker;
      worker.on(
        "message",
        (message: { id: number; result?: EmbeddingResult; error?: string }) => {
          const job = this.pending.get(message.id);
          if (!job) return;
          this.pending.delete(message.id);
          if (message.error) job.reject(Error(message.error));
          else if (message.result) job.resolve(message.result);
          else job.reject(Error("INVALID_TASK_EMBEDDING_RESPONSE"));
        },
      );
      worker.on("error", (error) => {
        if (this.worker === worker) {
          for (const job of this.pending.values()) job.reject(error);
          this.pending.clear();
          this.worker = undefined;
        }
      });
      worker.on("exit", () => {
        if (this.worker === worker) {
          this.worker = undefined;
          for (const job of this.pending.values())
            job.reject(Error("TASK_EMBEDDING_EXITED"));
          this.pending.clear();
        }
      });
    }
    const worker = this.worker;
    worker.ref();
    const id = ++this.sequence;
    const abort = () => this.close();
    signal?.addEventListener("abort", abort, { once: true });
    const timer = setTimeout(() => this.close(), settings.model_timeout_ms);
    try {
      const result = await new Promise<EmbeddingResult>((resolve, reject) => {
        this.pending.set(id, { resolve, reject });
        worker.postMessage({ id, texts, kind });
      });
      if (
        result.vectors.length !== texts.length ||
        result.vectors.some(
          (v) => v.length !== 384 || !v.every(Number.isFinite),
        )
      )
        throw Error("INVALID_TASK_EMBEDDING_RESPONSE");
      return result;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      worker.unref();
      if (this.worker === worker && !this.disposed) {
        this.idle = setTimeout(() => this.close(), settings.model_idle_ms);
        this.idle.unref();
      }
    }
  }
}
