import { isDeepStrictEqual } from "node:util";
import type {
  SessionEntry,
  SessionProjection,
} from "@earendil-works/pi-coding-agent";
import type { RequestMessages } from "./request-lifecycle.ts";

type Message = RequestMessages[number];
export const SOURCE_CACHE_LIMITS = Object.freeze({
  maxEntries: 8192,
  maxBytes: 16 * 1024 * 1024,
  keyChars: 256,
  idChars: 128,
});
interface Locator {
  key: string;
  index: number;
  bytes: number;
}
interface Bucket<T> {
  values: T[];
  cursor: number;
}
interface Pending {
  index: number;
  key: string;
}

/** Only a bounded locator key, never message text. Collisions are resolved by full comparison. */
function sourceKey(message: Message): string {
  const small = (value: unknown, chars: number) =>
    typeof value === "string"
      ? `${value.length}:${value.slice(0, chars)}`
      : typeof value === "number"
        ? String(value)
        : "?";
  const timestamp = "timestamp" in message ? message.timestamp : undefined;
  return `${small(message.role, 32)}|${small(timestamp, 32)}|${message.role === "toolResult" ? small(message.toolCallId, 96) : ""}`.slice(
    0,
    SOURCE_CACHE_LIMITS.keyChars,
  );
}
// A short slice/rope can otherwise retain the backing store of a very large opaque ID.
// Round-trip only the bounded UTF-16 units, preserving even unpaired surrogates.
const detached = (text: string): string =>
  Buffer.from(text, "utf16le").toString("utf16le");
function add<T>(buckets: Map<string, Bucket<T>>, key: string, value: T): void {
  const bucket = buckets.get(key);
  if (bucket) bucket.values.push(value);
  else buckets.set(key, { values: [value], cursor: 0 });
}
/** A cursor makes the ordinary ordered path cheap without forbidding reorders or duplicates. */
function matching<T>(
  bucket: Bucket<T> | undefined,
  equal: (value: T) => boolean,
): T | undefined {
  if (!bucket) return undefined;
  const { values, cursor } = bucket;
  let found = equal(values[cursor]!) ? cursor : -1;
  if (found === -1)
    found = values.findIndex((value, i) => i !== cursor && equal(value));
  if (found === -1) return undefined;
  bucket.cursor = (found + 1) % values.length;
  return values[found];
}

/** Per-WindowService hint cache. No message objects, SessionManager, projection or pass results are retained. */
export class SourceVerifier {
  readonly #maxEntries: number;
  readonly #maxBytes: number;
  readonly #locations = new Map<string, Locator>(); // In LRU order, oldest first.
  readonly #keys = new Map<string, Set<string>>();
  #bytes = 0;
  #sessionId: string | undefined;
  #last: { id: string; index: number } | undefined;

  constructor(limits: { maxEntries?: number; maxBytes?: number } = {}) {
    const entries = limits.maxEntries ?? SOURCE_CACHE_LIMITS.maxEntries;
    const bytes = limits.maxBytes ?? SOURCE_CACHE_LIMITS.maxBytes;
    if (
      !Number.isSafeInteger(entries) ||
      entries < 0 ||
      entries > SOURCE_CACHE_LIMITS.maxEntries ||
      !Number.isSafeInteger(bytes) ||
      bytes < 0 ||
      bytes > SOURCE_CACHE_LIMITS.maxBytes
    )
      throw Error("INVALID_SOURCE_CACHE_LIMIT");
    this.#maxEntries = entries;
    this.#maxBytes = bytes;
  }
  get stats() {
    return Object.freeze({
      entries: this.#locations.size,
      keys: this.#keys.size,
      bytes: this.#bytes,
    });
  }
  reset(): void {
    this.#locations.clear();
    this.#keys.clear();
    this.#bytes = 0;
    this.#sessionId = undefined;
    this.#last = undefined;
  }
  #remove(id: string): void {
    const old = this.#locations.get(id);
    if (!old) return;
    this.#locations.delete(id);
    this.#bytes -= old.bytes;
    const ids = this.#keys.get(old.key)!;
    ids.delete(id);
    if (!ids.size) this.#keys.delete(old.key);
  }
  #remember(id: string, index: number, key: string): void {
    if (id.length > SOURCE_CACHE_LIMITS.idChars || !this.#maxEntries) return;
    const bytes = 512 + 4 * (key.length + id.length);
    if (bytes > this.#maxBytes) return;
    this.#remove(id);
    while (
      this.#locations.size >= this.#maxEntries ||
      this.#bytes + bytes > this.#maxBytes
    )
      this.#remove(this.#locations.keys().next().value!);
    id = detached(id);
    key = detached(key);
    this.#locations.set(id, { key, index, bytes });
    this.#bytes += bytes;
    const ids = this.#keys.get(key);
    if (ids) ids.add(id);
    else this.#keys.set(key, new Set([id]));
  }
  #touch(id: string, locator: Locator): void {
    this.#locations.delete(id);
    this.#locations.set(id, locator);
  }

  match(
    messages: RequestMessages,
    entries: readonly SessionEntry[],
    sessionId: string,
    project: () => SessionProjection,
    signal?: AbortSignal,
  ) {
    signal?.throwIfAborted();
    const last = entries.at(-1);
    const cacheable =
      sessionId.length <= SOURCE_CACHE_LIMITS.idChars &&
      (!last || last.id.length <= SOURCE_CACHE_LIMITS.idChars);
    if (
      !cacheable ||
      this.#sessionId !== sessionId ||
      (this.#last && entries[this.#last.index]?.id !== this.#last.id)
    )
      this.reset();
    if (cacheable) {
      this.#sessionId = detached(sessionId);
      this.#last = last
        ? { id: detached(last.id), index: entries.length - 1 }
        : undefined;
    }
    const matched = new Array<boolean>(messages.length).fill(false);
    const pending: Pending[] = [];
    const cursors = new Map<string, SetIterator<string>>();
    let cacheHits = 0,
      rawScans = 0,
      projectionCalls = 0;
    for (const [i, message] of messages.entries()) {
      if ((i & 255) === 0) signal?.throwIfAborted();
      if (message.role === "system") {
        matched[i] = true;
        continue;
      }
      const key = sourceKey(message),
        ids = this.#keys.get(key);
      // Probe at most one locator. Collect misses rather than rescanning a colliding cache bucket.
      let cursor = cursors.get(key);
      if (!cursor && ids) {
        cursor = ids.values();
        cursors.set(key, cursor);
      }
      let candidate = cursor?.next();
      if (candidate?.done && ids) {
        cursor = ids.values();
        cursors.set(key, cursor);
        candidate = cursor.next();
      }
      const id = candidate?.value,
        locator = id === undefined ? undefined : this.#locations.get(id);
      const entry = locator ? entries[locator.index] : undefined;
      if (
        locator &&
        id !== undefined &&
        (entry?.id !== id || entry.type !== "message")
      )
        this.#remove(id);
      if (
        locator &&
        id !== undefined &&
        entry?.id === id &&
        entry.type === "message" &&
        isDeepStrictEqual(message, entry.message)
      ) {
        matched[i] = true;
        cacheHits++;
        this.#touch(id, locator);
      } else pending.push({ index: i, key });
    }
    let remaining = pending;
    if (pending.length) {
      rawScans++;
      const wanted = new Set(pending.map((p) => p.key));
      const buckets = new Map<string, Bucket<number>>();
      for (const [index, entry] of entries.entries()) {
        if ((index & 255) === 0) signal?.throwIfAborted();
        if (entry.type !== "message") continue;
        const key = sourceKey(entry.message);
        if (wanted.has(key)) add(buckets, key, index);
      }
      remaining = [];
      for (const item of pending) {
        const position = matching(buckets.get(item.key), (index) => {
          const entry = entries[index]!;
          return (
            entry.type === "message" &&
            isDeepStrictEqual(messages[item.index], entry.message)
          );
        });
        if (position === undefined) remaining.push(item);
        else {
          matched[item.index] = true;
          if (cacheable)
            this.#remember(entries[position]!.id, position, item.key);
        }
      }
    }
    if (remaining.length) {
      signal?.throwIfAborted();
      projectionCalls++;
      const projection = project();
      signal?.throwIfAborted();
      const wanted = new Set(remaining.map((p) => p.key));
      const buckets = new Map<string, Bucket<Message>>();
      for (const entry of projection.entries)
        for (const message of entry.messages) {
          const key = sourceKey(message);
          if (wanted.has(key)) add(buckets, key, message);
        }
      for (const item of remaining)
        matched[item.index] =
          matching(buckets.get(item.key), (candidate) =>
            isDeepStrictEqual(candidate, messages[item.index]),
          ) !== undefined;
    }
    signal?.throwIfAborted();
    return { matched, cacheHits, rawScans, projectionCalls };
  }
}
