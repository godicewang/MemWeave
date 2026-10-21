import { isAbsolute } from "node:path";
import { withLock } from "../../src/storage/files.ts";
const path = process.argv[2];
if (!path || !isAbsolute(path))
  throw Error("expected absolute fixture lock path");
await withLock(path, async () => {
  process.stdout.write("LOCK_READY\n");
  await new Promise<void>((resolve) => process.once("SIGTERM", resolve));
});
