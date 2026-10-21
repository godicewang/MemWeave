import type { ImageContent } from "@earendil-works/pi-ai";

/** Validate encoding/container signatures without changing the native bytes or resizing them. */
export function originalImage(
  value: unknown,
  maxBytes = 10 * 1024 * 1024,
): { image: ImageContent; bytes: number } {
  const image = value as Partial<ImageContent>;
  if (
    !image ||
    image.type !== "image" ||
    typeof image.data !== "string" ||
    typeof image.mimeType !== "string"
  )
    throw Error("UNSUPPORTED_ORIGINAL_MEDIA");
  if (
    !image.data.length ||
    image.data.length % 4 ||
    !/^[A-Za-z0-9+/]*={0,2}$/.test(image.data)
  )
    throw Error("INVALID_IMAGE_ENCODING");
  const size =
    (image.data.length / 4) * 3 -
    (image.data.endsWith("==") ? 2 : image.data.endsWith("=") ? 1 : 0);
  if (size > maxBytes) throw Error("IMAGE_BUDGET_EXCEEDED");
  const buffer = Buffer.from(image.data, "base64");
  if (buffer.toString("base64") !== image.data)
    throw Error("INVALID_IMAGE_ENCODING");
  const valid =
    image.mimeType === "image/png"
      ? buffer.length >= 33 &&
        buffer
          .subarray(0, 8)
          .equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])) &&
        buffer.toString("ascii", 12, 16) === "IHDR" &&
        buffer.readUInt32BE(16) > 0 &&
        buffer.readUInt32BE(20) > 0
      : image.mimeType === "image/jpeg"
        ? buffer.length >= 4 &&
          buffer[0] === 255 &&
          buffer[1] === 216 &&
          buffer.at(-2) === 255 &&
          buffer.at(-1) === 217
        : image.mimeType === "image/gif"
          ? buffer.length >= 14 &&
            /^GIF8[79]a$/.test(buffer.toString("ascii", 0, 6)) &&
            buffer.at(-1) === 59
          : image.mimeType === "image/webp"
            ? buffer.length >= 20 &&
              buffer.toString("ascii", 0, 4) === "RIFF" &&
              buffer.toString("ascii", 8, 12) === "WEBP" &&
              buffer.readUInt32LE(4) + 8 === buffer.length
            : false;
  if (!valid) throw Error("INVALID_OR_UNSUPPORTED_IMAGE");
  return {
    image: structuredClone(image as ImageContent),
    bytes: buffer.length,
  };
}
