import { createHash } from "node:crypto";
export function stableId(...parts: Array<string | number>): string {
  return createHash("sha256").update(JSON.stringify(parts)).digest("hex");
}
export function now(): string {
  return new Date().toISOString();
}
