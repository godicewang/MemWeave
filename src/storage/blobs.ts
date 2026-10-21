import { open, mkdir, rename, rm } from "node:fs/promises";
import { createHash } from "node:crypto";
import { isAbsolute } from "node:path";
import { parentPath, temporaryPath, type MemoryPaths } from "./paths.ts";

export class BlobStore {
  readonly paths: MemoryPaths;
  constructor(paths: MemoryPaths) {
    this.paths = paths;
  }
  async save(
    source: string,
  ): Promise<{ blob_hash: string; byte_length: number }> {
    if (!isAbsolute(source)) throw Error("INVALID_ORIGINAL_PATH");
    const temporary = temporaryPath(this.paths.blob("0".repeat(64)));
    await mkdir(parentPath(temporary), { recursive: true, mode: 0o700 });
    let input;
    try {
      input = await open(source, "r");
      if (!(await input.stat()).isFile()) throw Error("INVALID_ORIGINAL_FILE");
      const output = await open(temporary, "wx", 0o600),
        hash = createHash("sha256");
      let byte_length = 0;
      try {
        for await (const bytes of input.createReadStream({
          autoClose: false,
        })) {
          hash.update(bytes);
          byte_length += bytes.length;
          await output.writeFile(bytes);
        }
        await output.sync();
      } finally {
        await output.close();
      }
      const blob_hash = hash.digest("hex"),
        target = this.paths.blob(blob_hash);
      await rename(temporary, target);
      const directory = await open(parentPath(target), "r");
      try {
        await directory.sync();
      } finally {
        await directory.close();
      }
      return { blob_hash, byte_length };
    } finally {
      await input?.close();
      await rm(temporary, { force: true });
    }
  }
  /** Stream the whole hash/character count, retaining at most the requested range. */
  async text(
    original: { blob_hash: string; byte_length: number },
    offset: number,
    limit: number,
    budget: number,
  ) {
    const input = await open(this.paths.blob(original.blob_hash), "r");
    const hash = createHash("sha256"),
      decoder = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true });
    let byte_length = 0,
      total_chars = 0,
      content = "",
      returned = 0,
      afterCR = false;
    function consume(text: string) {
      for (let point of text) {
        if (point === "\u0000") throw Error("UNSUPPORTED_ORIGINAL_MEDIA");
        if (afterCR && point === "\n") {
          afterCR = false;
          continue;
        }
        afterCR = point === "\r";
        if (afterCR) point = "\n";
        if (total_chars >= offset && returned < Math.min(limit, budget)) {
          content += point;
          returned++;
        }
        total_chars++;
      }
    }
    try {
      if (!(await input.stat()).isFile()) throw Error("INVALID_BLOB_FILE");
      for await (const bytes of input.createReadStream({ autoClose: false })) {
        hash.update(bytes);
        byte_length += bytes.length;
        consume(decoder.decode(bytes, { stream: true }));
      }
      consume(decoder.decode());
      if (
        byte_length !== original.byte_length ||
        hash.digest("hex") !== original.blob_hash
      )
        throw Error("CORRUPT_ORIGINAL_BLOB");
      return {
        content,
        offset,
        total_chars,
        truncated: offset > 0 || returned < total_chars,
        range_complete:
          returned === Math.min(limit, Math.max(0, total_chars - offset)),
      };
    } catch (error) {
      if (
        (error as NodeJS.ErrnoException).code ===
        "ERR_ENCODING_INVALID_ENCODED_DATA"
      )
        throw Error("UNSUPPORTED_ORIGINAL_MEDIA: invalid UTF-8");
      throw error;
    } finally {
      await input.close();
    }
  }
}
