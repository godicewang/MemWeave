// Runs only after a clean npm ci. Import the public SDK and the complete host dependency graph.
import { CURRENT_SESSION_VERSION, VERSION } from "@earendil-works/pi-coding-agent";
import { createMemWeaveHost } from "./index.js";
import { PI_VERSION } from "./version.js";

if (VERSION !== PI_VERSION || typeof createMemWeaveHost !== "function") throw new Error("Invalid installed Pi SDK.");
console.log(JSON.stringify({ piVersion: VERSION, sessionVersion: CURRENT_SESSION_VERSION }));
