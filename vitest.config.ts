import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    testTimeout: 15_000,
    hookTimeout: 15_000,
    env: { PI_OFFLINE: "1", PI_TELEMETRY: "0" },
  },
});
