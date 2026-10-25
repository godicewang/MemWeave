import assert from "node:assert/strict";
import test from "node:test";
import { Type } from "typebox";
import {
  fauxAssistantMessage,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import {
  getCurrentSystemPrompt,
  getCurrentSystemMessage,
} from "@earendil-works/pi-ai";
import { taskSession } from "../fixtures/task-session.ts";
import { nativeSession } from "../fixtures/native-session.ts";
import { releaseFixture } from "../fixtures/release.ts";
import { registerMemweave } from "../../src/extension/register.ts";
test("production Runtime reload retains stable handler counts and Task State", async (t) => {
  const h = await taskSession(t);
  h.faux.setResponses([
    fauxAssistantMessage([
      fauxToolCall("task_create", {
        title: "Reload",
        goal: "Verify reload recovery",
        project_name: "MemWeave",
        summary: "Reload cognition",
        keywords: ["reload"],
      }),
    ]),
    fauxAssistantMessage("created"),
  ]);
  await h.session.prompt("create Task before reload");
  const scope = h.tasks.scope(h.session.extensionRunner!.createContext());
  const handlerCounts = () => h.loader.getExtensions().extensions.map(extension =>
    [...extension.handlers].map(([event, handlers]) => [event, handlers.length]));
  const initialHandlers = handlerCounts();
  for (let i = 0; i < 3; i++) {
    await h.session.reload();
    const before = h.frames.length;
    h.faux.setResponses([fauxAssistantMessage("after reload")]);
    await h.session.prompt(`reload ${i}`);
    assert.equal(h.frames.length, before + 1);
    assert.equal(
      h.tasks.scope(h.session.extensionRunner!.createContext()).task_id,
      scope.task_id,
    );
    assert.deepEqual(handlerCounts(), initialHandlers, "reload must not accumulate business or UI handlers");
    const last = h.frames.at(-1)!;
    assert.equal(
      last.filter(
        (m) => m.role === "custom" && m.customType === "memweave.state",
      ).length,
      1,
    );
  }
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
});
test("native dynamic descriptions and hidden declarations preserve Rule and conservatively budget active tool changes", async (t) => {
  let length = 10;
  const descriptions: string[] = [];
  const h = await taskSession(t, {
    extra: (pi) => {
      pi.registerTool({
        name: "dynamic_probe",
        label: "dynamic_probe",
        description: "base",
        parameters: Type.Object({}),
        prepareLoadout: () => ({
          descriptions: { dynamic_probe: "DYNAMIC_" + "x".repeat(length) },
          hiddenDeclarations: ["hidden_probe"],
        }),
        execute: async () => {
          length = 1000;
          return { content: [{ type: "text", text: "changed" }], details: {} };
        },
      });
      pi.registerTool({
        name: "hidden_probe",
        label: "hidden_probe",
        description: "hidden example",
        parameters: Type.Object({}),
        execute: async () => ({
          content: [{ type: "text", text: "hidden" }],
          details: {},
        }),
      });
    },
  });
  h.faux.setResponses([
    (context) => {
      descriptions.push(
        getCurrentSystemMessage(context.messages)!.toolsAdded!.find(
          (t) => t.name === "dynamic_probe",
        )!.description,
      );
      return fauxAssistantMessage([fauxToolCall("dynamic_probe", {})]);
    },
    (context) => {
      const system = getCurrentSystemMessage(context.messages)!;
      assert.ok(!system.toolsAdded!.some((t) => t.name === "hidden_probe"));
      assert.match(
        getCurrentSystemPrompt(context.messages),
        /pi_long_task_rule/,
      );
      descriptions.push(
        system.toolsAdded!.find((t) => t.name === "dynamic_probe")!.description,
      );
      return fauxAssistantMessage("done");
    },
  ]);
  await h.session.prompt("exercise native dynamic loadout");
  assert.equal(descriptions[0]!.length, 18);
  assert.equal(descriptions[1]!.length, 1008);
  assert.ok(h.budgets[1]!.R >= h.budgets[0]!.R + 990);
  assert.deepEqual(h.diagnostics, []);
  assert.deepEqual(h.errors, []);
});
test("unsupported forced-system counterexample: native projection after the hook replaces Rule", async (t) => {
  let actual = "";
  const h = await taskSession(t, {
    extra: (pi) =>
      pi.on("before_agent_start", () => ({
        systemPrompt: "FORCED_SYSTEM_ONLY",
      })),
  });
  h.faux.setResponses([
    (context) => {
      actual = getCurrentSystemPrompt(context.messages);
      return fauxAssistantMessage("counterexample");
    },
  ]);
  await h.session.prompt("show why this combination is outside support");
  assert.match(JSON.stringify(h.frames[0]), /pi_long_task_rule/);
  assert.equal(actual, "FORCED_SYSTEM_ONLY");
  assert.doesNotMatch(actual, /pi_long_task_rule/);
  assert.equal(h.faux.state.callCount, 1);
});
test("virtual routing is not silently budgeted using selected virtual limits", async (t) => {
  const f = await releaseFixture(t),
    diagnostics: string[] = [];
  const h = await nativeSession(t, [
    (pi) => {
      registerMemweave(pi, {
        paths: f.paths,
        report: (error) =>
          diagnostics.push(error instanceof Error ? error.message : "unknown"),
      });
    },
  ]);
  await h.runtime.setRuntimeApiKey("memweave-test", "local-test-only");
  h.runtime.registerVirtualModel({
    provider: "virtual-test",
    id: "route",
    name: "route",
    contextWindow: 1_048_576,
    maxTokens: 1024,
    route: () => ({ model: h.faux.getModel(), thinkingLevel: "off" }),
  });
  const model = h.runtime.getModel("virtual-test", "route");
  assert.ok(model);
  await h.session.setModel(model);
  await h.session.prompt("virtual request must be rejected before inference");
  assert.equal(h.faux.state.callCount, 0);
  assert.ok(
    diagnostics.some((message) => /MODEL_CAPACITY_UNVERIFIED/.test(message)),
    JSON.stringify({ diagnostics, errors: h.errors }),
  );
});
