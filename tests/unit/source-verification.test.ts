import assert from "node:assert/strict";
import test from "node:test";
import type {
  SessionEntry,
  SessionProjection,
} from "@earendil-works/pi-coding-agent";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import {
  SourceVerifier,
  SOURCE_CACHE_LIMITS,
} from "../../src/pi/source-verification.ts";

type MessageEntry = Extract<SessionEntry, { type: "message" }>;
type UserEntry = MessageEntry & {
  message: Extract<MessageEntry["message"], { role: "user" }>;
};
const user = (id: string, time = 1, content = id): UserEntry => ({
  type: "message",
  id,
  parentId: null,
  timestamp: "2026-10-24T00:00:00Z",
  message: { role: "user", content, timestamp: time },
});
const incoming = (entries: MessageEntry[]) =>
  structuredClone(entries.map((e) => e.message));
const emptyProjection = (): SessionProjection => ({
  entries: [],
  messages: [],
  thinkingLevel: "off",
  model: null,
});
const projected = (
  entry: MessageEntry,
  message: MessageEntry["message"],
): SessionProjection => ({
  ...emptyProjection(),
  entries: [{ sourceEntry: entry, messages: [message] }],
  messages: [message],
});

test("new copies are compared, warm cache skips source scans and normal requests never project", () => {
  const cache = new SourceVerifier(),
    entries = [user("one", 1), user("two", 2)];
  let projections = 0;
  const project = () => {
    projections++;
    return emptyProjection();
  };
  const first = cache.match(incoming(entries), entries, "s", project);
  assert.deepEqual(first.matched, [true, true]);
  assert.equal(first.rawScans, 1);
  const second = cache.match(
    incoming(entries),
    structuredClone(entries),
    "s",
    project,
  );
  assert.equal(second.cacheHits, 2);
  assert.equal(second.rawScans, 0);
  assert.equal(projections, 0);
  const added = [...entries, user("three", 3)];
  const next = cache.match(incoming(added), added, "s", project);
  assert.equal(next.cacheHits, 2);
  assert.equal(next.rawScans, 1);
  assert.deepEqual(next.matched, [true, true, true]);
});

test("warm cache does not trust unchanged IDs/timestamps or retain previous original objects", () => {
  const cache = new SourceVerifier(),
    entries = [user("one", 1, "old")],
    old = incoming(entries);
  cache.match(old, entries, "s", emptyProjection);
  const current = [user("one", 1, "changed in current snapshot")];
  const result = cache.match(old, current, "s", emptyProjection);
  assert.deepEqual(result.matched, [false]);
  assert.equal(result.projectionCalls, 1);
  const valid = cache.match(incoming(current), current, "s", emptyProjection);
  assert.deepEqual(valid.matched, [true]);
  assert.equal(valid.cacheHits, 1);
});

test("full nested arguments, reasoning/text/tool signatures and image bytes cannot be changed on a cache hit", () => {
  const assistant: MessageEntry = {
    ...user("assistant"),
    message: {
      ...fauxAssistantMessage([
        {
          type: "thinking",
          thinking: "reason",
          thinkingSignature: "reason-signature",
        },
        { type: "text", text: "signed", textSignature: "text-signature" },
        {
          ...fauxToolCall(
            "read",
            { path: "original", options: { offset: 7 } },
            { id: "call" },
          ),
          thoughtSignature: "call-signature",
        },
      ]),
      timestamp: 2,
    },
  };
  const image: MessageEntry = {
    ...user("image"),
    message: {
      role: "user",
      content: [
        { type: "image", data: "original-image", mimeType: "image/png" },
      ],
      timestamp: 3,
    },
  };
  const entries = [assistant, image],
    cache = new SourceVerifier();
  cache.match(incoming(entries), entries, "s", emptyProjection);
  const changes = [
    (m: typeof assistant.message) => {
      if (m.role === "assistant" && m.content[2]?.type === "toolCall")
        m.content[2].arguments.path = "changed";
    },
    (m: typeof assistant.message) => {
      if (m.role === "assistant" && m.content[0]?.type === "thinking")
        m.content[0].thinkingSignature = "changed";
    },
    (m: typeof assistant.message) => {
      if (m.role === "assistant" && m.content[1]?.type === "text")
        m.content[1].textSignature = "changed";
    },
    (m: typeof assistant.message) => {
      if (m.role === "assistant" && m.content[2]?.type === "toolCall")
        m.content[2].thoughtSignature = "changed";
    },
  ];
  for (const change of changes) {
    const copy = incoming([assistant]);
    change(copy[0]!);
    assert.deepEqual(cache.match(copy, entries, "s", emptyProjection).matched, [
      false,
    ]);
  }
  const copy = incoming([image]);
  const m = copy[0]!;
  if (
    m.role === "user" &&
    Array.isArray(m.content) &&
    m.content[0]?.type === "image"
  )
    m.content[0].data = "altered-image";
  assert.deepEqual(cache.match(copy, entries, "s", emptyProjection).matched, [
    false,
  ]);
  assert.equal(
    (entries[0]!.message as typeof assistant.message).role,
    "assistant",
  );
});

test("colliding lookup keys, reordered messages and duplicates still require exact candidate matches", () => {
  const entries = [user("one"), user("two"), user("three")],
    cache = new SourceVerifier();
  cache.match(incoming(entries), entries, "s", emptyProjection);
  const views = incoming([entries[2]!, entries[0]!, entries[2]!]);
  const result = cache.match(views, entries, "s", emptyProjection);
  assert.deepEqual(result.matched, [true, true, true]);
  assert.ok(result.rawScans <= 1);
  assert.equal(result.projectionCalls, 0);
  const forged = user("forged");
  assert.deepEqual(
    cache.match(incoming([forged]), entries, "s", emptyProjection).matched,
    [false],
  );
});

test("all cache misses are batched into one source scan and one lazy projection", () => {
  const entries = Array.from({ length: 1000 }, (_, i) => user(`m${i}`, i)),
    cache = new SourceVerifier();
  let calls = 0;
  const first = cache.match(incoming(entries), entries, "s", () => {
    calls++;
    return emptyProjection();
  });
  assert.equal(first.rawScans, 1);
  assert.equal(calls, 0);
  const bad = incoming([user("unknown-1", 2001), user("unknown-2", 2002)]);
  const result = cache.match(bad, entries, "s", () => {
    calls++;
    return emptyProjection();
  });
  assert.equal(result.rawScans, 1);
  assert.equal(result.projectionCalls, 1);
  assert.equal(calls, 1);
  assert.deepEqual(result.matched, [false, false]);
});

test("native projected messages are refreshed on every request and never retained as cache bodies", () => {
  const raw = user("one", 1, "original"),
    cache = new SourceVerifier();
  let view = "view A";
  const project = () => projected(raw, { ...raw.message, content: view });
  const request = incoming([user("one", 1, view)]);
  assert.deepEqual(cache.match(request, [raw], "s", project).matched, [true]);
  assert.equal(cache.stats.entries, 0);
  view = "view B";
  assert.deepEqual(cache.match(request, [raw], "s", project).matched, [false]);
  assert.deepEqual(
    cache.match(incoming([user("one", 1, view)]), [raw], "s", project).matched,
    [true],
  );
  assert.equal(cache.stats.entries, 0);
});

test("LRU evicts entries and empty buckets together, including byte-budget eviction", () => {
  const entries = [user("one", 1), user("two", 2), user("three", 3)],
    cache = new SourceVerifier({ maxEntries: 2 });
  cache.match(incoming(entries.slice(0, 2)), entries, "s", emptyProjection);
  cache.match(incoming([entries[0]!]), entries, "s", emptyProjection);
  cache.match(incoming([entries[2]!]), entries, "s", emptyProjection);
  assert.equal(cache.stats.entries, 2);
  assert.equal(cache.stats.keys, 2);
  assert.equal(
    cache.match(
      incoming([entries[0]!, entries[2]!]),
      entries,
      "s",
      emptyProjection,
    ).cacheHits,
    2,
  );
  assert.equal(
    cache.match(incoming([entries[1]!]), entries, "s", emptyProjection)
      .cacheHits,
    0,
  );
  const small = new SourceVerifier({ maxBytes: 1200 });
  small.match(incoming(entries), entries, "s", emptyProjection);
  assert.ok(small.stats.bytes <= 1200);
  assert.ok(small.stats.entries < 3);
  assert.equal(small.stats.keys, small.stats.entries);
  cache.reset();
  assert.deepEqual(cache.stats, { entries: 0, keys: 0, bytes: 0 });
});

test("changed source key removes the previous index; long IDs remain verifiable without caching", () => {
  const cache = new SourceVerifier(),
    entry = user("one", 1);
  cache.match(incoming([entry]), [entry], "s", emptyProjection);
  entry.message.timestamp = 2;
  cache.match(incoming([entry]), [entry], "s", emptyProjection);
  assert.equal(cache.stats.entries, 1);
  assert.equal(cache.stats.keys, 1);
  const long = user("x".repeat(129));
  assert.deepEqual(
    cache.match(incoming([long]), [long], "next", emptyProjection).matched,
    [true],
  );
  assert.equal(cache.stats.entries, 0);
});

test("Session identity, branch divergence and explicit lifecycle reset clear locators", () => {
  const cache = new SourceVerifier(),
    entries = [user("one", 1), user("two", 2)];
  cache.match(incoming(entries), entries, "s1", emptyProjection);
  assert.equal(
    cache.match(incoming(entries), entries, "s2", emptyProjection).cacheHits,
    0,
  );
  const branch = [entries[0]!, user("branch", 2)];
  assert.equal(
    cache.match(incoming(branch), branch, "s2", emptyProjection).cacheHits,
    0,
  );
  cache.reset();
  assert.equal(
    cache.match(incoming(branch), branch, "s2", emptyProjection).cacheHits,
    0,
  );
});

test("history larger than 8192 stays correct and cache accounting does not accumulate across requests", () => {
  const cache = new SourceVerifier(),
    entries = Array.from({ length: 10000 }, (_, i) =>
      user(`m${i}`, i, "body " + i),
    );
  for (let i = 0; i < 4; i++) {
    const result = cache.match(
      incoming(entries),
      entries,
      "s",
      emptyProjection,
    );
    assert.ok(result.matched.every(Boolean));
    assert.ok(result.rawScans <= 1);
    assert.equal(result.projectionCalls, 0);
    assert.equal(cache.stats.entries, SOURCE_CACHE_LIMITS.maxEntries);
    assert.equal(cache.stats.keys, cache.stats.entries);
    assert.ok(cache.stats.bytes <= SOURCE_CACHE_LIMITS.maxBytes);
  }
});

test("large bodies/IDs do not become cache keys; no message serialization is used", () => {
  const entry = user("one", 1, "x".repeat(2 * 1024 * 1024)),
    cache = new SourceVerifier();
  const copy = incoming([entry]);
  const original = JSON.stringify;
  JSON.stringify = () => {
    throw Error("message serialization forbidden");
  };
  try {
    assert.deepEqual(cache.match(copy, [entry], "s", emptyProjection).matched, [
      true,
    ]);
    assert.deepEqual(cache.match(copy, [entry], "s", emptyProjection).matched, [
      true,
    ]);
  } finally {
    JSON.stringify = original;
  }
  assert.ok(cache.stats.bytes < 2048);
});

test("projection errors and cancellation do not retain temporary data or approve unknown messages", () => {
  const raw = user("one", 1, "raw"),
    request = incoming([user("one", 1, "view")]),
    cache = new SourceVerifier();
  assert.throws(
    () =>
      cache.match(request, [raw], "s", () => {
        throw Error("native projection failed");
      }),
    /native projection failed/,
  );
  assert.deepEqual(cache.stats, { entries: 0, keys: 0, bytes: 0 });
  const controller = new AbortController();
  controller.abort();
  assert.throws(
    () => cache.match(request, [raw], "s", emptyProjection, controller.signal),
    /abort/i,
  );
  assert.deepEqual(cache.match(request, [raw], "s", emptyProjection).matched, [
    false,
  ]);
});

test("long opaque call IDs collide safely and cannot inflate retained locator data", () => {
  const id = "x".repeat(1024 * 1024);
  const entry: MessageEntry = {
    ...user("tool"),
    message: {
      role: "toolResult",
      toolCallId: id + "A",
      toolName: "read",
      content: [{ type: "text", text: "body" }],
      isError: false,
      timestamp: 1,
    },
  };
  const cache = new SourceVerifier();
  assert.deepEqual(
    cache.match(incoming([entry]), [entry], "s", emptyProjection).matched,
    [true],
  );
  const copy = incoming([entry]);
  if (copy[0]!.role === "toolResult") copy[0]!.toolCallId = id + "B";
  assert.deepEqual(cache.match(copy, [entry], "s", emptyProjection).matched, [
    false,
  ]);
  assert.ok(cache.stats.bytes < 2048);
});

test("cached array positions are hints: a different current entry ID is re-indexed even when content matches", () => {
  const tail: SessionEntry = {
    type: "custom",
    id: "tail",
    parentId: "old",
    timestamp: "2026-10-24",
    customType: "marker",
    data: {},
  };
  const cache = new SourceVerifier(),
    first = [user("old", 1, "same content"), tail];
  cache.match(incoming([first[0] as UserEntry]), first, "s", emptyProjection);
  const current = [user("new", 1, "same content"), tail];
  const result = cache.match(
    incoming([current[0] as UserEntry]),
    current,
    "s",
    emptyProjection,
  );
  assert.deepEqual(result.matched, [true]);
  assert.equal(result.cacheHits, 0);
  assert.equal(result.rawScans, 1);
  assert.equal(
    cache.match(
      incoming([current[0] as UserEntry]),
      current,
      "s",
      emptyProjection,
    ).cacheHits,
    1,
  );
});
