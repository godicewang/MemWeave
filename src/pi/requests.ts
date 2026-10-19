import { isDeepStrictEqual } from "node:util";
import type { Agent, AgentMessage, PrepareRequestContext } from "@earendil-works/pi-agent-core";
import { getCurrentSystemMessage, getSystemMessageText } from "@earendil-works/pi-ai";

/** Internal module boundary. Business preparation/selection stays outside the Pi adapter. */
export interface RequestPipeline<Frame> {
  prepare(request: PrepareRequestContext, signal?: AbortSignal): Promise<{
    frame: Frame;
    messages: AgentMessage[];
  }>;
  transform(messages: AgentMessage[], frame: Frame, signal?: AbortSignal): Promise<AgentMessage[]>;
}

interface ActiveRequest<Frame> {
  frame: Frame;
  systemText: string | undefined;
  expectedMessages?: AgentMessage[];
  ready: boolean;
  error?: Error;
}

export class RequestController<Frame> {
  private active: ActiveRequest<Frame> | undefined;
  private installed = false;
  private signal: AbortSignal | undefined;

  constructor(private readonly pipeline: RequestPipeline<Frame> | undefined) {}

  invalidate(): void { this.active = undefined; this.signal = undefined; }

  async transform(messages: AgentMessage[]): Promise<{ messages: AgentMessage[] } | undefined> {
    const active = this.active;
    if (!active || !this.pipeline) throw new Error("MemWeave request pipeline was not prepared.");
    try {
      this.signal?.throwIfAborted();
      const result = await this.pipeline.transform(messages, active.frame, this.signal);
      this.signal?.throwIfAborted();
      if (result.some((message) => message.role === "system")) {
        throw new Error("The context pipeline must not replace native system messages.");
      }
      active.expectedMessages = structuredClone(result);
      return { messages: result };
    } catch (error) {
      active.error = error instanceof Error ? error : new Error(String(error));
      // Pi catches extension errors. Keep failure state for the outer native-transform/send checks.
      return undefined;
    }
  }

  install(agent: Agent, validateRuntime: () => void = () => {}): void {
    if (this.installed) return;
    this.installed = true;
    const prepare = agent.prepareRequest?.bind(agent);
    const transform = agent.transformContext?.bind(agent);
    const stream = agent.streamFunction.bind(agent);

    agent.prepareRequest = async (request, signal) => {
      this.invalidate();
      validateRuntime();
      const native = (await prepare?.(request, signal)) ?? {};
      signal?.throwIfAborted();
      if (!this.pipeline) throw new Error("MemWeave request pipeline is not configured; refusing a bare request.");
      const current = {
        context: native.context ?? request.context,
        model: native.model ?? request.model,
        thinkingLevel: native.thinkingLevel ?? request.thinkingLevel,
      };
      const prepared = await this.pipeline.prepare(current, signal);
      signal?.throwIfAborted();
      const system = getCurrentSystemMessage(prepared.messages);
      this.signal = signal;
      this.active = {
        frame: prepared.frame, systemText: system ? getSystemMessageText(system) : undefined, ready: false,
      };
      return { ...native, context: { ...current.context, messages: prepared.messages } };
    };

    agent.transformContext = async (messages, signal) => {
      const result = transform ? await transform(messages, signal) : messages;
      const active = this.requireActive();
      if (active.error) throw active.error;
      if (!active.expectedMessages) throw new Error("MemWeave context pipeline did not assemble this request.");
      const system = getCurrentSystemMessage(result);
      if (!isDeepStrictEqual(result.filter((message) => message.role !== "system"), active.expectedMessages)
        || (system ? getSystemMessageText(system) : undefined) !== active.systemText) {
        throw new Error("Pi context changed after MemWeave assembly; check incompatible extensions or forced system prompts.");
      }
      signal?.throwIfAborted();
      active.ready = true;
      return result;
    };

    agent.streamFunction = (model, context, options) => {
      const active = this.requireActive();
      if (active.error) throw active.error;
      if (!active.ready) throw new Error("MemWeave refuses to send a request before successful context assembly.");
      options?.signal?.throwIfAborted();
      return stream(model, context, options);
    };
  }

  private requireActive(): ActiveRequest<Frame> {
    if (!this.active) throw new Error("MemWeave request pipeline has no current prepared request.");
    return this.active;
  }
}
