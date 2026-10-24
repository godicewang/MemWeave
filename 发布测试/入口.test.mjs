import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { copyFile, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const entry = fileURLToPath(new URL('./run.mjs', import.meta.url));
function invoke(args) {
  const env = { ...process.env };
  delete env.npm_execpath;
  return spawnSync(process.execPath, [entry, ...args], { env, encoding: 'utf8', timeout: 10_000 });
}

test('发布测试帮助不启动业务测试或要求私有认证', () => {
  const result = invoke(['--help']);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /--full/);
  assert.match(result.stdout, /不会发布/);
});

test('非法发布参数被拒绝，不能误当成完整验收', () => {
  const result = invoke(['--publish']);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /未知参数.*--publish/);
});

test('未通过 npm 启动时明确阻断，不继续跑测试', () => {
  const result = invoke([]);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /npm run test:release/);
});

test('完整模式在任何测试和真实 API 调用前拒绝脏候选', async (t) => {
  const root = await mkdtemp(join(tmpdir(), 'memweave-release-entry-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, '发布测试'));
  const copied = join(root, '发布测试/run.mjs');
  await copyFile(entry, copied);
  execFileSync('git', ['init', '--quiet', root]);
  execFileSync('git', ['-c', 'user.name=ReleaseFixture', '-c', 'user.email=release-fixture@example.invalid',
    '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '--quiet', '-m', 'fixture'], { cwd: root });
  const result = spawnSync(process.execPath, [copied, '--full'], {
    env: { ...process.env, npm_execpath: process.execPath }, encoding: 'utf8', timeout: 10_000 });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /工作区干净/);
  assert.doesNotMatch(result.stdout, /资源\/类型/);
});
