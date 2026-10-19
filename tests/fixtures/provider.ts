import {
  createAssistantMessageEventStream,
  InMemoryCredentialStore,
  type AssistantMessage,
  type Model,
  type Api,
  type TranscriptContext,
} from "@earendil-works/pi-ai";
import { ModelRuntime } from "@earendil-works/pi-coding-agent";

export function assistant(model: Model<Api>, content: AssistantMessage["content"] = [{ type: "text", text: "ok" }]): AssistantMessage {
  return {
    role: "assistant", content, api: model.api, provider: model.provider, model: model.id,
    usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
    stopReason: "stop", timestamp: Date.now(),
  };
}

export async function fakeProvider(respond?: (model: Model<Api>, index: number) => AssistantMessage) {
  const calls: TranscriptContext[] = [];
  const runtime = await ModelRuntime.create({
    credentials: new InMemoryCredentialStore(), modelsPath: null, refreshOnCreate: false,
  });
  runtime.registerProvider("memweave-fixture", {
    api: "openai-completions", apiKey: "fixture-credential", baseUrl: "https://fixture.invalid",
    models: [{ id: "fixture", name: "Fixture", reasoning: false, input: ["text", "image"],
      contextWindow: 4096, maxTokens: 512,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
    streamSimple(model, context) {
      calls.push(structuredClone(context));
      const stream = createAssistantMessageEventStream();
      queueMicrotask(() => {
        const message = respond?.(model, calls.length - 1) ?? assistant(model);
        if (message.stopReason === "pending") throw new Error("A fixture must return a completed response");
        if (message.stopReason === "error" || message.stopReason === "aborted") {
          stream.push({ type: "error", reason: message.stopReason, error: message });
        } else {
          stream.push({ type: "start", partial: message });
          stream.push({ type: "done", reason: message.stopReason, message });
        }
        stream.end();
      });
      return stream;
    },
  });
  const model = runtime.getModel("memweave-fixture", "fixture");
  if (!model) throw new Error("Fixture model not registered");
  return { modelRuntime: runtime, model, calls };
}
