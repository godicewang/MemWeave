import type { SettingsManager } from "@earendil-works/pi-coding-agent";

export class CompactionDisabledError extends Error {
  constructor() {
    super("MemWeave disables compaction for this runtime; shared Pi settings were not changed.");
    this.name = "CompactionDisabledError";
  }
}

const isolatedManagers = new WeakMap<SettingsManager, SettingsManager>();

/** Mask only effective compaction settings. Native methods retain their original receiver/storage. */
export function isolateCompaction(source: SettingsManager): SettingsManager {
  const existing = isolatedManagers.get(source);
  if (existing) return existing;
  const methods = new Map<PropertyKey, unknown>();
  const isolated = new Proxy(source, {
    get(target, property) {
      if (property === "getCompactionEnabled") return () => false;
      if (property === "getCompactionSettings") {
        return (...args: Parameters<SettingsManager["getCompactionSettings"]>) => ({
          ...target.getCompactionSettings(...args), enabled: false,
        });
      }
      if (property === "getSettings") return () => {
        const settings = target.getSettings();
        return { ...settings, compaction: { ...settings.compaction, enabled: false } };
      };
      if (property === "setCompactionEnabled") return (enabled: boolean) => {
        if (enabled) throw new CompactionDisabledError();
      };
      const value: unknown = Reflect.get(target, property, target);
      if (typeof value !== "function") return value;
      if (!methods.has(property)) methods.set(property, value.bind(target));
      return methods.get(property);
    },
  });
  isolatedManagers.set(source, isolated);
  isolatedManagers.set(isolated, isolated);
  return isolated;
}
