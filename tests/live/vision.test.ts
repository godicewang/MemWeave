import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  fauxProvider,
  fauxAssistantMessage as answer,
  fauxToolCall as call,
} from "@earendil-works/pi-ai/providers/faux";
import {
  productionTaskSession as taskSession,
  productionNativeSession as nativeSession,
} from "../fixtures/production-session.ts";
import { visionImage } from "../fixtures/vision-image.ts";
import {
  verifyProviderCapacity,
  type CapacityVerifier,
} from "../../src/pi/model-capacity.ts";
type Harness = Awaited<ReturnType<typeof taskSession>>;
interface Wire {
  images: { role: string; hash: string }[];
  textLeaksAnswer: boolean;
}
const instruction =
  "Read the actual image and describe the eight digits and the three shapes/colors from left to right. Any clear readable format is acceptable.";
const verifyCapacity: CapacityVerifier = (model, ctx) =>
  model.provider === "deepseek"
    ? verifyProviderCapacity(model, ctx)
    : Promise.resolve(model.contextWindow);
function observe(wires: Wire[], code: string) {
  return (pi: ExtensionAPI) => {
    pi.on("before_provider_request", (event, ctx) => {
      if (ctx.model?.provider !== "deepseek") return;
      const payload = event.payload as {
        messages: {
          role: string;
          content?:
            | string
            | { type: string; text?: string; image_url?: { url: string } }[];
        }[];
      };
      const images: Wire["images"] = [],
        text: string[] = [];
      for (const message of payload.messages) {
        if (typeof message.content === "string") text.push(message.content);
        else
          for (const part of message.content ?? []) {
            if (part.type === "text") text.push(part.text ?? "");
            if (part.type === "image_url") {
              assert.ok(part.image_url);
              images.push({
                role: message.role,
                hash: createHash("sha256")
                  .update(part.image_url.url)
                  .digest("hex"),
              });
            }
          }
      }
      wires.push({
        images,
        textLeaksAnswer: text.some((value) => value.includes(code)),
      });
    });
  };
}
async function credential(t: TestContext) {
  const path =
      process.env.MEMWEAVE_DEEPSEEK_AUTH ??
      join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json"),
    bytes = await readFile(path);
  t.after(async () => assert.ok(bytes.equals(await readFile(path))));
  const key = (JSON.parse(bytes.toString()) as { deepseek?: { key?: unknown } })
    .deepseek?.key;
  assert.equal(typeof key, "string");
  return key as string;
}
async function configure(h: Pick<Harness, "runtime" | "session">, key: string) {
  await h.runtime.setRuntimeApiKey("deepseek", key);
  const model = h.runtime.getModel("deepseek", "deepseek-flash");
  assert.ok(model);
  assert.ok(model.input.includes("image"));
  await h.session.setModel(model);
}
function completed(
  h: Pick<Harness, "session" | "errors">,
  t: TestContext,
  code: string,
) {
  const final = h.session.agent.state.messages.at(-1);
  assert.ok(final?.role === "assistant" && final.stopReason === "stop");
  const text = final.content
    .filter((p) => p.type === "text")
    .map((p) => p.text)
    .join("\n");
  assert.ok(text.trim());
  assert.deepEqual(h.errors, []);
  // Recognition and formatting are capability observations, not the plugin transport contract.
  t.diagnostic(
    JSON.stringify({
      compatibility: "provider accepted native image and completed",
      ocrContainsExpectedDigitsIgnoringWhitespace: text
        .replace(/\s/g, "")
        .includes(code),
      recognitionPreview: text.slice(0, 300),
    }),
  );
}
test(
  "real DeepSeek image provider compatibility; OCR/format are reported separately",
  { timeout: 60000 },
  async (t) => {
    const key = await credential(t),
      fixture = visionImage(),
      wires: Wire[] = [];
    const h = await nativeSession(t, [observe(wires, fixture.code)]);
    await configure(h, key);
    await h.session.prompt(instruction, { images: [fixture.image] });
    assert.ok(wires.length >= 1);
    assert.equal(wires[0]!.images.length, 1);
    assert.equal(wires[0]!.images[0]!.role, "user");
    assert.equal(wires[0]!.textLeaksAnswer, false);
    completed(h, t, fixture.code);
    t.diagnostic(
      `${wires.length} real API requests; direct provider control, no MemWeave Window`,
    );
  },
);
test(
  "real DeepSeek accepts the unchanged R image read through the complete installed protocol",
  { timeout: 60000 },
  async (t) => {
    const key = await credential(t),
      fixture = visionImage(),
      wires: Wire[] = [];
    const source = await taskSession(t),
      create = {
        title: "Vision source",
        goal: "Verify image reads",
        project_name: "MemWeave",
        summary: "Visual source",
        keywords: ["vision"],
      };
    source.faux.setResponses([
      answer([call("task_create", create)]),
      answer("created"),
    ]);
    await source.session.prompt("Create source Task");
    source.faux.setResponses([answer("picture saved")]);
    await source.session.prompt(
      "Stored picture source. No textual description supplied.",
      { images: [fixture.image] },
    );
    const task = (await source.tasks.index.read())[0]!;
    const h = await taskSession(t, {
      paths: source.paths,
      verifyCapacity,
      extra: observe(wires, fixture.code),
    });
    h.faux.setResponses([
      answer([call("task_create", { ...create, title: "Vision consumer" })]),
      answer("created"),
    ]);
    await h.session.prompt("Create consumer Task");
    // Arrange reads deterministically with actual native tools. Agent choice of references is a separate behavior test.
    const imageSetup = fauxProvider({
      provider: "memweave-test",
      models: [
        {
          id: "image-setup",
          input: ["text", "image"],
          contextWindow: 1048576,
          maxTokens: 1024,
        },
      ],
      tokensPerSecond: Infinity,
    });
    h.runtime.registerNativeProvider(imageSetup.provider);
    await h.session.setModel(imageSetup.getModel());
    imageSetup.setResponses([
      answer([
        call("memory_read", { items: [{ ref: "U2", task_id: task.task_id }] }),
      ]),
      answer("source located"),
    ]);
    await h.session.prompt("Locate the known picture source");
    const located = h.manager
      .getBranch()
      .findLast(
        (e) =>
          e.type === "message" &&
          e.message.role === "toolResult" &&
          e.message.toolName === "memory_read",
      );
    assert.ok(
      located?.type === "message" &&
        located.message.role === "toolResult" &&
        !located.message.isError,
    );
    const text = located.message.content.find((p) => p.type === "text");
    assert.ok(text);
    const item = (
      JSON.parse(text.text) as {
        items: { status: string; attachments: { ref: string }[] }[];
      }
    ).items[0]!;
    assert.equal(item.status, "ok");
    assert.ok(item.attachments[0]);
    imageSetup.setResponses([
      answer([
        call("memory_read", { items: [{ ref: item.attachments[0].ref }] }),
      ]),
      answer("image returned"),
    ]);
    await h.session.prompt("Read that actual attachment");
    const result = h.manager
      .getBranch()
      .findLast(
        (e) =>
          e.type === "message" &&
          e.message.role === "toolResult" &&
          e.message.toolName === "memory_read",
      );
    assert.ok(
      result?.type === "message" &&
        result.message.role === "toolResult" &&
        !result.message.isError,
    );
    const returned = result.message.content.find((p) => p.type === "image");
    assert.ok(returned);
    assert.equal(returned.data, fixture.image.data);
    assert.equal(returned.mimeType, fixture.image.mimeType);
    await configure(h, key);
    await h.session.prompt(instruction);
    assert.ok(wires.length >= 1);
    assert.equal(wires[0]!.images.length, 1);
    assert.equal(wires[0]!.images[0]!.role, "user");
    assert.equal(wires[0]!.textLeaksAnswer, false);
    assert.equal(
      wires[0]!.images[0]!.hash,
      createHash("sha256")
        .update(`data:${returned.mimeType};base64,${returned.data}`)
        .digest("hex"),
    );
    completed(h, t, fixture.code);
    assert.deepEqual(h.diagnostics, []);
    t.diagnostic(
      `${wires.length} real API requests after scripted native source/read setup; full Pi System, Rule, tools and Window; image bytes/hash preserved`,
    );
  },
);
