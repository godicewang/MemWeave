import { open, mkdir, rename, rm, readFile } from "node:fs/promises";
import { setTimeout } from "node:timers/promises";
import { parentPath, temporaryPath, lockOwnerPath } from "./paths.ts";
export function isMissing(error: unknown): boolean {
  return (error as NodeJS.ErrnoException)?.code === "ENOENT";
}
export async function readOptional(file: string): Promise<string | undefined> {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(
      await readFile(file),
    );
  } catch (error) {
    if (isMissing(error)) return undefined;
    throw error;
  }
}
/** Same-directory rename is the commit point. A directory-sync failure is explicitly indeterminate. */
export async function atomicWrite(file: string, bytes: string): Promise<void> {
  await mkdir(parentPath(file), { recursive: true, mode: 0o700 });
  const temporary = temporaryPath(file);
  try {
    const fd = await open(temporary, "wx", 0o600);
    try {
      await fd.writeFile(bytes);
      await fd.sync();
    } finally {
      await fd.close();
    }
    await rename(temporary, file);
    try {
      const directory = await open(parentPath(file), "r");
      try {
        await directory.sync();
      } finally {
        await directory.close();
      }
    } catch {
      throw Error(
        "COMMIT_DURABILITY_UNCERTAIN: replacement completed; retry with the same operation",
      );
    }
  } finally {
    await rm(temporary, { force: true });
  }
}
/** Cross-process mutex. A dead owner is diagnosed, never silently stolen during another writer's commit. */
export async function withLock<T>(
  lock: string,
  work: () => Promise<T>,
  signal?: AbortSignal,
): Promise<T> {
  await mkdir(parentPath(lock), { recursive: true, mode: 0o700 });
  const deadline = Date.now() + 15_000;
  for (;;) {
    signal?.throwIfAborted();
    try {
      await mkdir(lock, { mode: 0o700 });
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      const owner = await readOptional(lockOwnerPath(lock));
      if (owner && /^\d+$/.test(owner)) {
        try {
          process.kill(Number(owner), 0);
        } catch (e) {
          if ((e as NodeJS.ErrnoException).code === "ESRCH")
            throw Error(
              "LOCK_OWNER_DEAD: inspect and remove the stale memory lock before retrying",
            );
        }
      }
      if (Date.now() > deadline)
        throw Error("LOCK_TIMEOUT: another writer holds the memory lock");
      await setTimeout(15, undefined, signal ? { signal } : {});
    }
  }
  try {
    const owner = await open(lockOwnerPath(lock), "wx", 0o600);
    try {
      await owner.writeFile(String(process.pid));
    } finally {
      await owner.close();
    }
    return await work();
  } finally {
    await rm(lock, { recursive: true, force: true });
  }
}
