interface Part {
  type?: unknown;
  text?: unknown;
  id?: unknown;
  name?: unknown;
  mimeType?: unknown;
}
export function normalizeMessage(value: unknown) {
  const message = value as {
    role?: unknown;
    content?: unknown;
    details?: { truncation?: { truncated?: unknown } };
  };
  if (
    !message ||
    !["user", "assistant", "toolResult"].includes(String(message.role))
  )
    throw Error("UNSUPPORTED_SOURCE_MESSAGE");
  const content = message.content;
  if (typeof content !== "string" && !Array.isArray(content))
    throw Error("CORRUPT_SOURCE_CONTENT");
  const parts: Part[] =
    typeof content === "string" ? [{ type: "text", text: content }] : content;
  const text: string[] = [],
    attachments: { part_index: number; media_type: string }[] = [],
    tool_calls: { id: string; name: string }[] = [];
  let supported = true;
  for (const [index, part] of parts.entries()) {
    if (!part || typeof part !== "object") {
      supported = false;
      continue;
    }
    if (part.type === "text" && typeof part.text === "string")
      text.push(part.text);
    else if (part.type === "image" && typeof part.mimeType === "string")
      attachments.push({ part_index: index, media_type: part.mimeType });
    else if (
      message.role === "assistant" &&
      part.type === "toolCall" &&
      typeof part.id === "string" &&
      typeof part.name === "string"
    )
      tool_calls.push({ id: part.id, name: part.name });
    else if (!(message.role === "assistant" && part.type === "thinking"))
      supported = false;
  }
  return {
    text: text.join("\n").replace(/\r\n?/g, "\n"),
    attachments,
    tool_calls,
    source_complete:
      supported && message.details?.truncation?.truncated !== true,
    supported,
  };
}
export function textRange(
  text: string,
  offset: number,
  limit: number,
  budget = limit,
) {
  const points = [...text],
    wanted = Math.min(limit, Math.max(0, points.length - offset));
  const size = Math.min(wanted, budget);
  return {
    content: points.slice(offset, offset + size).join(""),
    offset,
    total_chars: points.length,
    truncated: offset > 0 || size < points.length,
    range_complete: size === wanted,
  };
}
