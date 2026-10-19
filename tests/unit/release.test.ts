import { describe, expect, it } from "vitest";
import { assertCompatible, parseRelease, releaseId } from "../../src/install/artifact.js";

const release = () => ({
  format: 1,
  version: "0.1.0-dev.0",
  piVersion: "1.3.0",
  sessionVersion: 3,
  environment: { node: "24.22.0", npm: "11.19.1", platform: "darwin", arch: "arm64" },
  dataCompatibility: "pi-session-3;memory-unimplemented",
  files: { "package.json": "a".repeat(64), "install-lock.json": "b".repeat(64) },
});

describe("release metadata boundary", () => {
  it("has a stable content identity and detects changed contents", () => {
    const first = parseRelease(release());
    expect(releaseId(first)).toBe(releaseId(parseRelease(release())));
    expect(releaseId({ ...first, files: { ...first.files, "README.md": "c".repeat(64) } })).not.toBe(releaseId(first));
  });

  it.each(["../auth.json", "/tmp/file", "dist/../secret", "dist/link\\file", "docs/specs/rule.md", "node_modules/pi/index.js"])(
    "rejects paths outside the runtime whitelist: %s", (path) => {
      expect(() => parseRelease({ ...release(), files: { [path]: "a".repeat(64) } })).toThrow(/path/);
    },
  );

  it("rejects unknown formats, invalid versions, digests and incomplete environments", () => {
    for (const change of [{ format: 2 }, { version: "../../file" }, { files: { "README.md": "invalid" } }, { environment: {} }]) {
      expect(() => parseRelease({ ...release(), ...change })).toThrow();
    }
  });

  it("blocks a data format change instead of attempting a migration", () => {
    const first = parseRelease(release());
    expect(() => assertCompatible(first, { ...first, version: "0.1.1" })).not.toThrow();
    expect(() => assertCompatible(first, { ...first, sessionVersion: 4 })).toThrow(/compatib/);
    expect(() => assertCompatible(first, { ...first, dataCompatibility: "new-format" })).toThrow(/compatib/);
  });
});
