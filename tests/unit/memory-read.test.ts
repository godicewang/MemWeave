import assert from "node:assert/strict";
import test from "node:test";
import { Check } from "typebox/value";
import { MemoryReadSchema } from "../../src/memory/model.ts";
import { normalizeMessage, textRange } from "../../src/memory/text.ts";
import { originalImage } from "../../src/pi/original-image.ts";

test("memory_read validates known refs, safe integer offsets and the fixed total ceiling", () => {
  for (const input of [
    { items: [{ ref: "U1" }] },
    { items: [{ ref: "R2", offset: 0, limit: 1 }], max_total_chars: 50000 },
    { items: [{ ref: "T9", task_id: "task_other" }] },
  ])
    assert.ok(Check(MemoryReadSchema, input));
  for (const input of [
    { items: [] },
    { items: [{ ref: "F1" }] },
    { items: [{ ref: "T0" }] },
    { items: [{ ref: "U1", offset: -1 }] },
    { items: [{ ref: "A1", limit: 0 }] },
    { items: [{ ref: "U1", offset: Number.MAX_SAFE_INTEGER + 1 }] },
    { items: [{ ref: "U1", path: "/tmp/arbitrary" }] },
    { items: [{ ref: "U1" }], max_total_chars: 50001 },
  ])
    assert.equal(Check(MemoryReadSchema, input), false);
});

test("images reject invalid base64, unsupported containers and byte overrun before sending", () => {
  assert.throws(
    () =>
      originalImage({
        type: "image",
        mimeType: "image/png",
        data: "not base64!",
      }),
    /INVALID_IMAGE_ENCODING/,
  );
  assert.throws(
    () =>
      originalImage({
        type: "image",
        mimeType: "application/pdf",
        data: Buffer.from("pdf").toString("base64"),
      }),
    /INVALID_OR_UNSUPPORTED_IMAGE/,
  );
  assert.throws(
    () =>
      originalImage(
        {
          type: "image",
          mimeType: "image/png",
          data: Buffer.alloc(100).toString("base64"),
        },
        99,
      ),
    /IMAGE_BUDGET_EXCEEDED/,
  );
});

test("normalization and slices use code points without trimming, NFC or broken emoji", () => {
  const text = normalizeMessage({
    role: "user",
    content: [
      { type: "text", text: " a\r\n😀e\u0301" },
      { type: "text", text: "后\r末 " },
    ],
    timestamp: 0,
  });
  assert.equal(text.text, " a\n😀e\u0301\n后\n末 ");
  assert.deepEqual(textRange(text.text, 3, 3), {
    content: "😀e\u0301",
    offset: 3,
    total_chars: 11,
    truncated: true,
    range_complete: true,
  });
  assert.equal(textRange(text.text, 999, 10).content, "");
});

test("text projection keeps native call identities separate from protected fields and attachments", () => {
  const normalized = normalizeMessage({
    role: "assistant",
    content: [
      {
        type: "thinking",
        thinking: "private reasoning",
        thinkingSignature: "opaque",
      },
      { type: "text", text: "visible", textSignature: "preserved in Session" },
      {
        type: "toolCall",
        id: "native|id",
        name: "bash",
        arguments: { command: "secret parameter" },
      },
    ],
  });
  assert.equal(normalized.text, "visible");
  assert.deepEqual(normalized.tool_calls, [{ id: "native|id", name: "bash" }]);
  assert.equal(normalized.source_complete, true);
  assert.equal(
    normalizeMessage({ role: "user", content: [{ type: "future-binary" }] })
      .source_complete,
    false,
  );
  assert.equal(
    normalizeMessage({
      role: "toolResult",
      content: [{ type: "text", text: "tail" }],
      details: { truncation: { truncated: true } },
    }).source_complete,
    false,
  );
});
