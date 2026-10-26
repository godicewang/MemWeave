import { parentPort, workerData } from "node:worker_threads";
import { readFile } from "node:fs/promises";
import { Tokenizer } from "@huggingface/tokenizers";
import { InferenceSession, Tensor } from "onnxruntime-node";
const tokenizer = new Tokenizer(
  JSON.parse(await readFile(String(workerData.tokenizer), "utf8")),
  JSON.parse(await readFile(String(workerData.tokenizerConfig), "utf8")),
);
const session = await InferenceSession.create(String(workerData.model), {
  executionProviders: ["cpu"],
  intraOpNumThreads: 2,
});
async function run(message: {
  id: number;
  texts: string[];
  kind: "query" | "passage";
}) {
  try {
    const vectors: number[][] = [],
      truncated: boolean[] = [];
    for (const text of message.texts) {
      const encoded = tokenizer.encode(`${message.kind}: ${text}`).ids;
      const tooLong = encoded.length > 512;
      if (tooLong && message.kind === "query")
        throw Error(
          "TASK_SEARCH_QUERY_TOO_LONG: maximum 512 model tokens; shorten the query",
        );
      // Keep the model's final separator when limiting a passage, as its standard tokenizer does.
      const ids = tooLong
        ? [...encoded.slice(0, 511), encoded.at(-1)!]
        : encoded;
      const feeds: Record<string, Tensor> = {};
      for (const name of session.inputNames) {
        if (!["input_ids", "attention_mask", "token_type_ids"].includes(name))
          throw Error("UNSUPPORTED_TASK_MODEL_INPUT");
        const values =
          name === "input_ids"
            ? ids
            : ids.map(() => (name === "attention_mask" ? 1 : 0));
        feeds[name] = new Tensor("int64", BigInt64Array.from(values, BigInt), [
          1,
          ids.length,
        ]);
      }
      let outputs: Awaited<ReturnType<typeof session.run>> | undefined;
      try {
        outputs = await session.run(feeds);
        const hidden =
          outputs.last_hidden_state ?? outputs[session.outputNames[0]!];
        if (
          !hidden ||
          hidden.dims.length !== 3 ||
          hidden.dims[1] !== ids.length ||
          hidden.dims[2] !== 384
        )
          throw Error("INVALID_TASK_MODEL_OUTPUT");
        const vector = Array<number>(384).fill(0);
        for (let t = 0; t < ids.length; t++)
          for (let i = 0; i < 384; i++)
            vector[i]! += Number(hidden.data[t * 384 + i]) / ids.length;
        const norm = Math.hypot(...vector);
        if (!Number.isFinite(norm) || norm === 0)
          throw Error("INVALID_TASK_EMBEDDING");
        vectors.push(vector.map((v) => v / norm));
        truncated.push(tooLong);
      } finally {
        for (const output of Object.values(outputs ?? {})) output.dispose();
        for (const input of Object.values(feeds)) input.dispose();
      }
    }
    parentPort!.postMessage({ id: message.id, result: { vectors, truncated } });
  } catch (error) {
    parentPort!.postMessage({
      id: message.id,
      error: error instanceof Error ? error.message : "TASK_EMBEDDING_FAILED",
    });
  }
}
let queue = Promise.resolve();
parentPort!.on(
  "message",
  (message: Parameters<typeof run>[0] | { close: true }) => {
    queue = queue.then(async () => {
      if ("close" in message) {
        await session.release();
        parentPort!.close();
      } else await run(message);
    });
  },
);
