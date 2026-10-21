import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm, stat, readdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import test from "node:test";
import { BlobStore } from "../../src/storage/blobs.ts";
import { memoryPaths } from "../../src/storage/paths.ts";

test("blob streaming preserves bytes, deduplicates, normalizes split CRLF/emoji, checks hash and private modes", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-blob-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const paths = memoryPaths(root),
    store = new BlobStore(paths),
    source = join(root, "source");
  const text = "a".repeat(65535) + "\r\n😀e\u0301\r结束 ",
    bytes = Buffer.from(text);
  await writeFile(source, bytes);
  const original = await store.save(source);
  assert.equal(
    original.blob_hash,
    createHash("sha256").update(bytes).digest("hex"),
  );
  assert.deepEqual(await store.save(source), original);
  assert.equal((await readdir(join(root, "blobs"))).length, 1);
  assert.equal(
    (await stat(paths.blob(original.blob_hash))).mode & 0o777,
    0o600,
  );
  const range = await store.text(original, 65535, 5, 4);
  assert.equal(range.content, "\n😀e\u0301");
  assert.equal(range.range_complete, false);
  assert.equal(range.total_chars, 65543);
  await writeFile(paths.blob(original.blob_hash), "corrupted");
  await assert.rejects(
    store.text(original, 0, 10, 10),
    /CORRUPT_ORIGINAL_BLOB/,
  );
  assert.throws(() => paths.blob("../outside"), /INVALID_BLOB_HASH/);
});

test("blob rejects invalid UTF-8, binary NUL and source directory; failed saves leave no staging files", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "memweave-blob-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const store = new BlobStore(memoryPaths(root)),
    source = join(root, "source");
  await assert.rejects(store.save(root), /INVALID_ORIGINAL_FILE/);
  assert.deepEqual(await readdir(join(root, "blobs")), []);
  await writeFile(source, Buffer.from([255]));
  await assert.rejects(store.text(await store.save(source), 0, 10, 10));
  await writeFile(source, "one\0two");
  await assert.rejects(
    store.text(await store.save(source), 0, 10, 10),
    /UNSUPPORTED_ORIGINAL_MEDIA/,
  );
});
