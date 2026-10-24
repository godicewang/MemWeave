import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { access, mkdir, readFile, readdir, rm } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { DefaultResourceLoader, SessionManager, SettingsManager, VERSION } from '@earendil-works/pi-coding-agent';
import { packArtifact, releaseFixture, releaseWorker, repository, unpackArtifact } from '../tests/fixtures/release.ts';

const digest = (bytes) => `sha512-${createHash('sha512').update(bytes).digest('base64')}`;

test('同一候选的可重复归档保持发布边界，并通过已打包代码的独立进程功能恢复', { timeout: 120_000 }, async (t) => {
  const f = await releaseFixture(t);
  const archive = await packArtifact(f.root);
  const integrity = digest(await readFile(archive));
  const repeated = join(f.root, 'repeated');
  await mkdir(repeated);
  assert.equal(digest(await readFile(await packArtifact(repeated))), integrity, '同一候选两次打包必须一致');
  const artifact = await unpackArtifact(f.root, archive);
  const files = (await readdir(artifact, { recursive: true, withFileTypes: true }))
    .filter((item) => item.isFile())
    .map((item) => join(item.parentPath, item.name).slice(artifact.length + 1).replaceAll('\\', '/')).sort();
  const sources = (await readdir(join(repository, 'src'), { recursive: true }))
    .filter((file) => file.endsWith('.ts')).map((file) => `src/${file.replaceAll('\\', '/')}`);
  const expected = ['LICENSE', 'README.md', 'USER_GUIDE.md', 'package.json', 'src/config/defaults.json',
    'resources/rule.md', ...(await readdir(join(repository, 'resources/tokenizer'))).map((name) => `resources/tokenizer/${name}`), ...sources].sort();
  assert.deepEqual(files, expected, '发布流程/测试/内部文档/凭据不得进入产物');
  for (const file of files) assert.deepEqual(await readFile(join(artifact, file)), await readFile(join(repository, file)), `包内文件偏离候选：${file}`);
  const manifest = JSON.parse(await readFile(join(artifact, 'package.json'), 'utf8'));
  assert.deepEqual(manifest.pi.extensions, ['./src/extension/index.ts']);
  for (const peer of ['@earendil-works/pi-ai', '@earendil-works/pi-coding-agent', 'typebox']) {
    assert.equal(manifest.peerDependencies[peer], '*');
    assert.equal(manifest.dependencies?.[peer], undefined);
    await assert.rejects(access(join(artifact, 'node_modules', peer)), { code: 'ENOENT' });
    await assert.rejects(access(join(dirname(artifact), 'node_modules', peer)), { code: 'ENOENT' });
  }
  const agentDir = join(f.root, 'loader-agent');
  await mkdir(agentDir);
  const loader = new DefaultResourceLoader({ cwd: f.cwd, agentDir,
    settingsManager: SettingsManager.create(f.cwd, agentDir, { projectTrusted: true }),
    additionalExtensionPaths: [join(artifact, 'src/extension/index.ts')],
    noSkills: true, noThemes: true, noPromptTemplates: true });
  await loader.reload();
  assert.deepEqual(loader.getExtensions().errors, []);
  assert.equal(loader.getExtensions().extensions.length, 1);
  assert.equal(loader.getAgentsFiles().agentsFiles.length, 0);

  const before = await releaseWorker({ ...f.base, artifact, action: 'create', label: 'candidate-created' });
  const task = JSON.parse(await readFile(f.paths.index, 'utf8'))[0];
  const stateBefore = await readFile(f.paths.state(task));
  const original = SessionManager.open(before.sessionFile).getBranch().filter((entry) => entry.type === 'message');
  const configBefore = await readFile(f.paths.config);
  await rm(f.paths.view(task));
  const after = await releaseWorker({ ...f.base, artifact, action: 'recover', sessionFile: before.sessionFile, taskId: before.taskId, label: 'candidate-recovered' });
  assert.equal(after.taskId, before.taskId);
  assert.equal(after.version, 3);
  assert.equal(after.window, true);
  assert.equal(after.settings, 4);
  assert.ok((await readFile(f.paths.state(task))).subarray(0, stateBefore.length).equals(stateBefore));
  assert.deepEqual(await readFile(f.paths.config), configBefore);
  await access(f.paths.view(task));
  const recovered = SessionManager.open(after.sessionFile).getBranch();
  for (const entry of original) assert.deepEqual(recovered.find((item) => item.id === entry.id), entry);
  t.diagnostic(JSON.stringify({ name: manifest.name, version: manifest.version, host: VERSION, integrity,
    files: files.length, localHttpRequests: before.requests + after.requests, realModelRequests: 0 }));
});
