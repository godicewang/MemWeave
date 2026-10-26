import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Check } from "typebox/value";
import { CLARIFY_TOOL_NAME, ClarifySchema } from "../task/model.ts";

export function registerTaskClarification(pi: ExtensionAPI): void {
  pi.registerTool({
    name: CLARIFY_TOOL_NAME,
    label: "请求用户澄清",
    description:
      "Ask only when missing information blocks the CURRENT requested step or Task choice. Registering an explicitly named Goal does not require later implementation details. Required question. Call ALONE, without other tools in the same batch. Stops automatic execution until actual user input; never guesses a Task, creates a placeholder Goal or changes State. Native UI collects a real reply; without UI or when cancelled, displays the question and waits for the next user message.",
    parameters: ClarifySchema,
    executionMode: "sequential",
    async execute(_id, params, signal, update, ctx) {
      if (!Check(ClarifySchema, params)) throw Error("INVALID_TASK_CLARIFICATION");
      signal?.throwIfAborted();
      const details: {
        status: "waiting_for_user" | "input_queued";
        question: string;
      } = { status: "waiting_for_user", question: params.question };
      update?.({ content: [{ type: "text", text: `等待用户澄清：${params.question}` }], details });
      if (ctx.hasUI) {
        const reply = await ctx.ui.input(
          params.question, undefined, signal ? { signal } : undefined,
        );
        signal?.throwIfAborted();
        if (reply?.trim()) {
          pi.sendUserMessage(reply, { deliverAs: "followUp", expandPromptTemplates: false });
          details.status = "input_queued";
        }
      }
      return {
        content: [{ type: "text", text: `${params.question}\n\n${details.status === "input_queued"
          ? "已收到用户输入，由下一条真实用户消息继续。"
          : "等待用户补充后继续；本轮停止，不自动选择或创建任务。"}` }],
        details,
        terminate: true,
      };
    },
  });
}
