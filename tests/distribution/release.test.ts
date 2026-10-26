import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { access, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import {
  DefaultPackageManager,
  DefaultResourceLoader,
  SettingsManager,
} from "@earendil-works/pi-coding-agent";
import {
  packArtifact,
  releaseFixture,
  releaseWorker,
  sourceArtifact,
  repository,
} from "../fixtures/release.ts";

test("temporary npm registry: installed release upgrade recovers real Task/State/Session and removal preserves them", async (t) => {
  const f = await releaseFixture(t);
  const old = await sourceArtifact(f.root, "9868254");
  const current = JSON.parse(
    await readFile(join(repository, "package.json"), "utf8"),
  );
  const packageName = current.name as string,
    targetVersion = current.version as string;
  const oldManifest = JSON.parse(
    await readFile(join(old, "package.json"), "utf8"),
  );
  await writeFile(
    join(old, "package.json"),
    JSON.stringify({ ...oldManifest, name: packageName }),
  );
  await writeFile(f.paths.rule, await readFile(join(old, "resources/rule.md")));
  const artifacts = new Map<string, Buffer>([
    [
      "0.0.0-before",
      await readFile(await packArtifact(f.root, old, "0.0.0-before")),
    ],
    [targetVersion, await readFile(await packArtifact(f.root))],
  ]);
  // Serve the real installed runtime dependency closure. A tokenizer-only
  // registry would reject the new local CPU search runtime during an upgrade.
  const dependencies = new Map<
    string,
    {
      manifest: Record<string, unknown> & {
        name: string;
        version: string;
        dependencies?: Record<string, string>;
      };
      bytes: Buffer;
      route: string;
    }
  >();
  async function collect(name: string) {
    if (dependencies.has(name)) return;
    const directory = join(repository, "node_modules", name),
      manifest = JSON.parse(
        await readFile(join(directory, "package.json"), "utf8"),
      );
    const destination = join(f.root, "dependencies", String(dependencies.size));
    await mkdir(destination, { recursive: true });
    const bytes = await readFile(await packArtifact(destination, directory));
    dependencies.set(name, {
      manifest,
      bytes,
      route: `/dependency-${dependencies.size}.tgz`,
    });
    for (const child of Object.keys(manifest.dependencies ?? {}))
      await collect(child);
  }
  for (const name of new Set([
    ...Object.keys(oldManifest.dependencies ?? {}),
    ...Object.keys(current.dependencies ?? {}),
  ]))
    await collect(name);
  const manifests = new Map([
    [
      "0.0.0-before",
      JSON.parse(await readFile(join(old, "package.json"), "utf8")),
    ],
    [targetVersion, current],
  ]);
  let origin = "";
  const served = new Set<string>();
  const server = createServer((request, response) => {
    const dependency = dependencies.get(
      decodeURIComponent(request.url ?? "").slice(1),
    );
    if (dependency) {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({
          name: dependency.manifest.name,
          "dist-tags": { latest: dependency.manifest.version },
          versions: {
            [dependency.manifest.version]: {
              ...dependency.manifest,
              dist: {
                tarball: `${origin}${dependency.route}`,
                integrity: `sha512-${createHash("sha512").update(dependency.bytes).digest("base64")}`,
              },
            },
          },
        }),
      );
      return;
    }
    const tarball = [...dependencies.values()].find(
      (d) => d.route === request.url,
    );
    if (tarball) {
      served.add(tarball.manifest.name);
      response.writeHead(200, { "content-type": "application/octet-stream" });
      response.end(tarball.bytes);
      return;
    }

    if (decodeURIComponent(request.url ?? "") === `/${packageName}`) {
      const versions = Object.fromEntries(
        [...artifacts].map(([version, bytes]) => [
          version,
          {
            ...manifests.get(version),
            name: packageName,
            version,
            dist: {
              tarball: `${origin}/memweave/-/memweave-${version}.tgz`,
              integrity: `sha512-${createHash("sha512").update(bytes).digest("base64")}`,
            },
          },
        ]),
      );
      response.writeHead(200, { "content-type": "application/json" });
      response.end(
        JSON.stringify({
          name: packageName,
          "dist-tags": { next: targetVersion },
          versions,
        }),
      );
      return;
    }
    const version = [...artifacts.keys()].find(
      (version) => request.url === `/memweave/-/memweave-${version}.tgz`,
    );
    if (version) {
      served.add(version);
      response.writeHead(200, { "content-type": "application/octet-stream" });
      response.end(artifacts.get(version));
      return;
    }
    response.writeHead(404);
    response.end();
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(async () => {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) =>
      server.close((error) => (error ? reject(error) : resolve())),
    );
  });
  origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const agentDir = join(f.root, "agent");
  await mkdir(agentDir);
  const auth = join(agentDir, "auth.json"),
    authValue = '{"fixture":"private authentication sentinel"}';
  await writeFile(auth, authValue);
  await writeFile(
    join(agentDir, "settings.json"),
    JSON.stringify({
      compaction: { enabled: false },
      npmCommand: [
        "npm",
        "--registry",
        origin,
        "--cache",
        join(f.root, "registry-cache"),
        "--no-audit",
        "--no-fund",
      ],
    }),
  );
  const settings = SettingsManager.create(f.cwd, agentDir, {
    projectTrusted: true,
  });
  const manager = new DefaultPackageManager({
    cwd: f.cwd,
    agentDir,
    settingsManager: settings,
  });
  const loader = new DefaultResourceLoader({
    cwd: f.cwd,
    agentDir,
    settingsManager: settings,
    noSkills: true,
    noThemes: true,
    noPromptTemplates: true,
  });
  const initial = `npm:${packageName}@0.0.0-before`,
    target = `npm:${packageName}@${targetVersion}`;
  await manager.installAndPersist(initial, { local: true });
  await settings.flush();
  const installed = manager.getInstalledPath(initial, "project");
  assert.ok(installed);
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  assert.equal(loader.getExtensions().extensions.length, 1);
  const before = await releaseWorker({
    ...f.base,
    artifact: installed,
    action: "create",
    label: "registry-before",
  });
  assert.equal(before.version, 2);
  assert.equal(before.window, false);
  const task = JSON.parse(await readFile(f.paths.index, "utf8"))[0];
  const stateBefore = await readFile(f.paths.state(task), "utf8"),
    configBefore = await readFile(f.paths.config);
  const setup = f.paths.setup(join(f.root, "setup-agent"));
  await mkdir(join(f.paths.root, "setup"));
  await writeFile(
    setup.marker,
    '{"version":2,"package_version":"0.0.0-before"}',
  );
  await writeFile(f.paths.rule, "CUSTOM RULE FROM PREVIOUS NPM VERSION");
  const messagesBefore = (await readFile(before.sessionFile, "utf8"))
    .trimEnd()
    .split("\n")
    .map((line) => JSON.parse(line))
    .filter((entry) => entry.type === "message");
  settings.setProjectPackages([target]);
  await settings.flush();
  await manager.update(target);
  // Pi intentionally skips exact npm versions during update. Explicit install
  // reconciles a changed pinned npm version; changing settings alone does not.
  assert.equal(
    JSON.parse(await readFile(join(installed, "package.json"), "utf8")).version,
    "0.0.0-before",
  );
  await manager.installAndPersist(target, { local: true });
  await settings.flush();
  assert.equal(manager.getInstalledPath(target, "project"), installed);
  assert.equal(
    JSON.parse(await readFile(join(installed, "package.json"), "utf8")).version,
    targetVersion,
  );
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  assert.equal(loader.getExtensions().extensions.length, 1);
  assert.equal(loader.getAgentsFiles().agentsFiles.length, 0);
  await rm(f.paths.view(task));
  const after = await releaseWorker({
    ...f.base,
    artifact: installed,
    sessionFile: before.sessionFile,
    taskId: before.taskId,
    action: "recover",
    label: "registry-after",
  });
  assert.equal(after.version, 3);
  assert.equal(after.window, true);
  assert.equal(after.settings, 4);
  const upgradedRule = await readFile(f.paths.rule);
  assert.ok(
    upgradedRule.equals(await readFile(join(installed, "resources/rule.md"))),
  );
  assert.deepEqual(JSON.parse(await readFile(setup.marker, "utf8")), {
    version: 2,
    package_version: targetVersion,
  });
  await assert.rejects(access(setup.settings), { code: "ENOENT" });
  assert.ok(
    (await readFile(f.paths.state(task), "utf8")).startsWith(stateBefore),
  );
  await access(f.paths.view(task));
  const messagesAfter = (await readFile(before.sessionFile, "utf8"))
    .trimEnd()
    .split("\n")
    .map((line) => JSON.parse(line))
    .filter((entry) => entry.type === "message");
  assert.deepEqual(
    messagesAfter.slice(0, messagesBefore.length),
    messagesBefore,
  );
  for (const file of ["AGENTS.md", "docs", "tests", "scripts"])
    await assert.rejects(access(join(installed, file)), { code: "ENOENT" });
  for (const peer of [
    "@earendil-works/pi-ai",
    "@earendil-works/pi-coding-agent",
    "typebox",
  ])
    await assert.rejects(access(join(installed, "node_modules", peer)), {
      code: "ENOENT",
    });
  const stateAfter = await readFile(f.paths.state(task)),
    sessionAfter = await readFile(before.sessionFile);
  settings.setProjectPackages([{ source: target, extensions: [] }]);
  await settings.flush();
  await loader.reload();
  assert.equal(loader.getExtensions().extensions.length, 0);
  settings.setProjectPackages([target]);
  await settings.flush();
  await loader.reload();
  assert.equal(loader.getExtensions().extensions.length, 1);
  assert.equal(await manager.removeAndPersist(target, { local: true }), true);
  await settings.flush();
  await loader.reload();
  assert.equal(loader.getExtensions().extensions.length, 0);
  await assert.rejects(access(installed), { code: "ENOENT" });
  for (const [path, value] of [
    [f.paths.config, configBefore],
    [f.paths.rule, upgradedRule],
    [f.paths.state(task), stateAfter],
    [before.sessionFile, sessionAfter],
  ] as const)
    assert.ok(value.equals(await readFile(path)));
  assert.equal(await readFile(auth, "utf8"), authValue);
  assert.equal(settings.getCompactionEnabled(), false);
  assert.deepEqual(
    [...served].sort(),
    [targetVersion, "0.0.0-before", ...dependencies.keys()].sort(),
  );
  t.diagnostic(
    "Local registry protocol only, not npmjs.org: two installed versions; Rule refreshed from actual package version without settings writes; independent Pi processes; 7 local HTTP model requests; no real inference",
  );
});
