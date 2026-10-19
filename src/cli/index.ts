#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { PI_VERSION } from "../pi/version.js";

try {
  if (process.argv[2] === "manage") {
    await (await import("../install/cli.js")).manage(process.argv.slice(3));
  } else {
    const { values } = parseArgs({ options: { help: { type: "boolean", short: "h" }, version: { type: "boolean", short: "v" } } });
    if (values.version) {
      const metadata: unknown = JSON.parse(readFileSync(new URL("../../package.json", import.meta.url), "utf8"));
      if (!metadata || typeof metadata !== "object" || !("version" in metadata) || typeof metadata.version !== "string") {
        throw new Error("Invalid MemWeave installation metadata.");
      }
      console.log(`MemWeave ${metadata.version} (Pi SDK ${PI_VERSION})`);
    } else {
      console.log("MemWeave — development foundation\n\nUsage: memweave --help | --version | manage --help\n\nSDK host/adapter is available. Task, Rule, State, Window and the interactive CLI are not connected yet.");
    }
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
