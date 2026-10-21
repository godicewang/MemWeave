import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import test, { type TestContext } from "node:test";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import { taskSession } from "../fixtures/task-session.ts";
import { nativeSession } from "../fixtures/native-session.ts";
import { visionImage } from "../fixtures/vision-image.ts";
import {
  verifyProviderCapacity,
  type CapacityVerifier,
} from "../../src/pi/model-capacity.ts";

type Harness = Awaited<ReturnType<typeof taskSession>>;
interface Wire {
  model: string;
  images: { role: string; hash: string }[];
  text_leaks_answer: boolean;
}
const instruction =
  "Read only the actual image. Return ONLY a JSON object with keys code (the eight digits at the top as a string), left, middle, right. Each spatial key must have shape and color in lowercase English. Identify the three shapes in the bottom row. Do not add markdown.";
const verifyCapacity: CapacityVerifier = (model, ctx) =>
  model.provider === "deepseek"
    ? verifyProviderCapacity(model, ctx)
    : Promise.resolve(model.contextWindow);

function observe(wires: Wire[], code: string) {
  return (pi: ExtensionAPI) => {
    pi.on("before_provider_request", (event) => {
      const payload = event.payload as {
        model: string;
        messages: {
          role: string;
          content?:
            | string
            | { type: string; text?: string; image_url?: { url: string } }[];
        }[];
      };
      const images: Wire["images"] = [],
        text: string[] = [];
      for (const message of payload.messages ?? []) {
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
        model: payload.model,
        images,
        text_leaks_answer: text.join("\n").includes(code),
      });
    });
  };
}
async function credential(t: TestContext): Promise<string> {
  const file =
    process.env.MEMWEAVE_DEEPSEEK_AUTH ??
    join(homedir(), ".local/share/memweave-dev/pi-agent/auth.json");
  const original = await readFile(file);
  t.after(async () => assert.ok(original.equals(await readFile(file))));
  const value = (
    JSON.parse(original.toString()) as {
      deepseek?: { type?: string; key?: unknown };
    }
  ).deepseek;
  assert.ok(value?.type === "api_key" && typeof value.key === "string");
  return value.key;
}
async function configure(h: Pick<Harness, "runtime" | "session">, key: string) {
  await h.runtime.setRuntimeApiKey("deepseek", key);
  const model = h.runtime.getModel("deepseek", "deepseek-flash");
  assert.ok(model);
  assert.ok(model.input.includes("image"));
  await h.session.setModel(model);
}
function checkAnswer(
  h: Pick<Harness, "session" | "errors" | "diagnostics">,
  code: string,
) {
  const final = h.session.agent.state.messages.at(-1);
  assert.ok(final?.role === "assistant" && final.stopReason === "stop");
  const text = final.content
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n")
    .trim();
  const answer = JSON.parse(
    text.slice(text.indexOf("{"), text.lastIndexOf("}") + 1),
  );
  assert.equal(String(answer.code), code);
  assert.deepEqual(answer.left, { shape: "circle", color: "red" });
  assert.deepEqual(answer.middle, { shape: "square", color: "blue" });
  assert.deepEqual(answer.right, { shape: "triangle", color: "green" });
  assert.deepEqual(h.errors, []);
  assert.deepEqual(h.diagnostics, []);
}

test(
  "real DeepSeek vision: direct PNG OCR and spatial shape/color recognition",
  { timeout: 60_000 },
  async (t) => {
    const key = await credential(t),
      fixture = visionImage(),
      wires: Wire[] = [];
    // Provider capability baseline deliberately has no MemWeave Window: production defaults
    // replace pictures with R and require an established Task before attachment input.
    const h = await nativeSession(t, [observe(wires, fixture.code)]);
    await configure(h, key);
    h.session.setActiveToolsByName([]);
    await h.session.prompt(instruction, { images: [fixture.image] });
    checkAnswer({ ...h, diagnostics: [] }, fixture.code);
    assert.equal(wires.length, 1);
    assert.equal(wires[0]!.images.length, 1);
    assert.equal(wires[0]!.images[0]!.role, "user");
    assert.equal(wires[0]!.text_leaks_answer, false);
    t.diagnostic(
      "1 real DeepSeek inference; random eight-digit OCR and three shapes/colors correct; no answer in request text",
    );
  },
);

test(
  "real DeepSeek vision: blind cross-Task R image read through native Pi tool encoding",
  { timeout: 60_000 },
  async (t) => {
    const key = await credential(t),
      fixture = visionImage(),
      wires: Wire[] = [];
    const source = await taskSession(t);
    const create = {
      title: "Vision source",
      goal: "Verify image reads",
      project_name: "MemWeave",
      summary: "Visual source",
      keywords: ["vision"],
    };
    source.faux.setResponses([
      fauxAssistantMessage([fauxToolCall("task_create", create)]),
      fauxAssistantMessage("created"),
    ]);
    await source.session.prompt(
      "Create the source Task before providing an attachment.",
    );
    source.faux.setResponses([
      fauxAssistantMessage("source stored by reference"),
    ]);
    await source.session.prompt(
      "Stored picture source. No textual description is supplied.",
      { images: [fixture.image] },
    );
    const task = (await source.tasks.index.read())[0];
    assert.ok(task);
    const h = await taskSession(t, {
      paths: source.paths,
      verifyCapacity,
      extra: observe(wires, fixture.code),
    });
    h.faux.setResponses([
      fauxAssistantMessage([
        fauxToolCall("task_create", { ...create, title: "Vision consumer" }),
      ]),
      fauxAssistantMessage("created"),
    ]);
    await h.session.prompt("Create a separate image consumer Task.");
    wires.length = 0;
    await configure(h, key);
    h.session.setActiveToolsByName(["memory_read"]);
    await h.session.prompt(
      `First call memory_read with items=[{"ref":"U2","task_id":"${task.task_id}"}]. Then call memory_read explicitly on the attachment R reference it returns (do not guess it). The current Session has never seen the picture. Only after the image has actually been returned, ${instruction}`,
    );
    assert.ok(wires.length >= 3);
    assert.equal(wires[0]!.images.length, 0);
    assert.equal(wires[1]!.images.length, 0);
    assert.equal(wires.at(-1)!.images.length, 1);
    assert.ok(
      wires.every(
        (wire) =>
          !wire.text_leaks_answer &&
          wire.images.every((image) => image.role === "user"),
      ),
    );
    const results = h.manager
      .getEntries()
      .filter(
        (entry) =>
          entry.type === "message" &&
          entry.message.role === "toolResult" &&
          entry.message.toolName === "memory_read",
      );
    assert.equal(results.length, 2);
    for (const entry of results)
      assert.ok(
        entry.type === "message" &&
          entry.message.role === "toolResult" &&
          !entry.message.isError,
      );
    const original = source.manager
      .getEntries()
      .find(
        (entry) =>
          entry.type === "message" &&
          entry.message.role === "user" &&
          Array.isArray(entry.message.content) &&
          entry.message.content.some((p) => p.type === "image"),
      );
    assert.ok(
      original?.type === "message" &&
        original.message.role === "user" &&
        Array.isArray(original.message.content),
    );
    const image = original.message.content.find(
      (part) => part.type === "image",
    );
    assert.ok(image);
    const last = results.at(-1);
    assert.ok(last?.type === "message" && last.message.role === "toolResult");
    const returned = last.message.content.find((part) => part.type === "image");
    assert.ok(returned);
    assert.equal(returned.data, image.data);
    assert.equal(
      wires.at(-1)!.images[0]!.hash,
      createHash("sha256")
        .update(`data:${returned.mimeType};base64,${returned.data}`)
        .digest("hex"),
    );
    checkAnswer(h, fixture.code);
    t.diagnostic(
      `${wires.length} real DeepSeek inference requests; 5 Faux setup requests; wire image counts ${JSON.stringify(wires.map((wire) => wire.images.length))}; native image bytes preserved; OCR/shapes/colors correct`,
    );
  },
);
