import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFile } from 'node:child_process';
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { isAbsolute, join } from 'node:path';
import { promisify } from 'node:util';

const run = promisify(execFile);
const sourceName = '@godice/memweave';
const targetName = '@godicewang/memweave';
const version = '0.1.0';
const sourceIntegrity = 'sha512-9Yys8Z4yCTc/sKL/dD0xTXNfQFZF5Ee5rGlApU1IH4jd6I0c9edAQNcqAaLuZvIxPlP9u02eafbe1TPOkEELBA==';
const registry = 'https://npm.pkg.github.com';
const root = process.argv[2];
assert(root && isAbsolute(root), 'Provide a new absolute temporary output directory');
await mkdir(root);

async function download(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(60_000) });
  assert(response.ok, `Download failed: HTTP ${response.status}`);
  return response;
}
const metadata = await (await download(`https://registry.npmjs.org/${encodeURIComponent(sourceName)}/${version}`)).json();
assert.equal(metadata.name, sourceName);
assert.equal(metadata.version, version);
assert.equal(metadata.dist.integrity, sourceIntegrity);
const sourceUrl = new URL(metadata.dist.tarball);
assert.equal(sourceUrl.protocol, 'https:');
assert.equal(sourceUrl.hostname, 'registry.npmjs.org');
const sourceBytes = Buffer.from(await (await download(sourceUrl)).arrayBuffer());
const integrity = (bytes) => `sha512-${createHash('sha512').update(bytes).digest('base64')}`;
assert.equal(integrity(sourceBytes), sourceIntegrity);
await writeFile(join(root, 'npm-source.tgz'), sourceBytes);
const source = join(root, 'source');
await mkdir(source);
await run('tar', ['-xzf', join(root, 'npm-source.tgz'), '-C', source]);
const packageRoot = join(source, 'package');

async function files(directory, prefix = '') {
  const entries = [];
  for (const item of await readdir(join(directory, prefix), { withFileTypes: true })) {
    const relative = prefix ? `${prefix}/${item.name}` : item.name;
    if (item.isDirectory()) entries.push(...await files(directory, relative));
    else {
      assert(item.isFile(), `Unexpected non-file: ${relative}`);
      entries.push(relative);
    }
  }
  return entries.sort();
}
const originalFiles = await files(packageRoot);
assert.equal(originalFiles.length, 59);
for (const file of originalFiles) {
  assert(/^(package\.json|README\.md|USER_GUIDE\.md|LICENSE|src\/.+\.ts|src\/config\/defaults\.json|resources\/rule\.md|resources\/tokenizer\/[^/]+)$/.test(file), `Unexpected package file: ${file}`);
}
const originals = new Map(await Promise.all(originalFiles.map(async (file) => [file, await readFile(join(packageRoot, file))])));
const originalManifest = JSON.parse(originals.get('package.json'));
assert.equal(originalManifest.name, sourceName);
assert.equal(originalManifest.version, version);
assert.equal(originalManifest.license, 'MIT');
assert.equal(originalManifest.repository.url, 'git+https://github.com/godicewang/MemWeave.git');
const manifest = structuredClone(originalManifest);
manifest.name = targetName;
manifest.publishConfig.registry = registry;
const manifestBytes = Buffer.from(`${JSON.stringify(manifest, null, 2)}\n`);
await writeFile(join(packageRoot, 'package.json'), manifestBytes);
const packed = join(root, 'packed');
await mkdir(packed);
const { stdout } = await run('npm', ['pack', '--json', '--ignore-scripts', '--pack-destination', packed], { cwd: packageRoot });
const [pack] = JSON.parse(stdout);
const archive = join(packed, pack.filename);
const checked = join(root, 'checked');
await mkdir(checked);
await run('tar', ['-xzf', archive, '-C', checked]);
const checkedRoot = join(checked, 'package');
assert.deepEqual(await files(checkedRoot), originalFiles);
for (const file of originalFiles) {
  assert.deepEqual(await readFile(join(checkedRoot, file)), file === 'package.json' ? manifestBytes : originals.get(file), `Changed package file: ${file}`);
}
const archiveIntegrity = integrity(await readFile(archive));
assert.equal(archiveIntegrity, pack.integrity);
console.log(JSON.stringify({ name: targetName, version, registry, tag: 'next', source: `${sourceName}@${version}`, sourceIntegrity, archive, integrity: archiveIntegrity, files: originalFiles.length, unchangedFiles: originalFiles.length - 1 }));
