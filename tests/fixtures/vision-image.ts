import { randomInt } from "node:crypto";
import { crc32, deflateSync } from "node:zlib";
import type { ImageContent } from "@earendil-works/pi-ai";

/** The answer exists only in pixels; no caption, file name or PNG text metadata carries it. */
export function visionImage(): { code: string; image: ImageContent } {
  const code = String(randomInt(10_000_000, 100_000_000));
  const width = 900,
    height = 480;
  const raw = Buffer.alloc(height * (width * 3 + 1), 255);
  for (let y = 0; y < height; y++) raw[y * (width * 3 + 1)] = 0;
  const pixel = (x: number, y: number, color: readonly number[]) => {
    if (x < 0 || x >= width || y < 0 || y >= height) return;
    const index = y * (width * 3 + 1) + 1 + x * 3;
    raw[index] = color[0]!;
    raw[index + 1] = color[1]!;
    raw[index + 2] = color[2]!;
  };
  const rect = (
    x: number,
    y: number,
    w: number,
    h: number,
    color: readonly number[],
  ) => {
    for (let row = y; row < y + h; row++)
      for (let column = x; column < x + w; column++) pixel(column, row, color);
  };
  const digits = [
    ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    ["11111", "10000", "10000", "11110", "00001", "00001", "11110"],
    ["01110", "10000", "10000", "11110", "10001", "10001", "01110"],
    ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    ["01110", "10001", "10001", "01111", "00001", "00001", "01110"],
  ];
  for (let digit = 0; digit < 8; digit++)
    for (let y = 0; y < 7; y++)
      for (let x = 0; x < 5; x++) {
        if (digits[Number(code[digit])]![y]![x] === "1")
          rect(100 + digit * 85 + x * 12, 50 + y * 12, 12, 12, [0, 0, 0]);
      }
  for (let y = 265; y <= 395; y++)
    for (let x = 85; x <= 215; x++) {
      if ((x - 150) ** 2 + (y - 330) ** 2 <= 65 ** 2)
        pixel(x, y, [225, 25, 30]);
    }
  rect(385, 265, 130, 130, [20, 70, 230]);
  for (let y = 265; y <= 395; y++) {
    const half = (y - 265) / 2;
    for (let x = Math.ceil(750 - half); x <= Math.floor(750 + half); x++)
      pixel(x, y, [0, 170, 40]);
  }
  function chunk(type: string, data: Buffer): Buffer {
    const body = Buffer.concat([Buffer.from(type), data]),
      result = Buffer.alloc(data.length + 12);
    result.writeUInt32BE(data.length);
    body.copy(result, 4);
    result.writeUInt32BE(crc32(body), result.length - 4);
    return result;
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;
  const png = Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
  return {
    code,
    image: {
      type: "image",
      mimeType: "image/png",
      data: png.toString("base64"),
    },
  };
}
