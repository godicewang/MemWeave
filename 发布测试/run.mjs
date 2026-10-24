import { spawn, execFile } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const root = fileURLToPath(new URL('../', import.meta.url));
const exec = promisify(execFile);
const allowed = new Set(['--help', '--full', '--distribution', '--live']);

async function main() {
  const args = process.argv.slice(2);
  for (const arg of args) if (!allowed.has(arg)) throw Error(`未知参数：${arg}；使用 --help 查看用法`);
  if (args.includes('--help')) {
    console.log('npm run test:release [-- --full | --distribution | --live]\n默认：常规回归、构建、候选产物功能验收。\n--distribution：补 npm/Git 安装升级卸载；固定当前 HEAD，需先 push。\n--live：补产物的真实 DeepSeek 冒烟，读取仓库外私有配置并产生 API 调用。\n--full：全部阶段，要求干净候选；发布前仍须核对兼容与专项矩阵。\n此入口不会发布，不修改远端标签或用户全局 Pi。');
    return;
  }
  const npm = process.env.npm_execpath;
  if (!npm) throw Error('请通过 npm run test:release 启动，确保候选打包使用同一 npm CLI');
  const full = args.includes('--full');
  const distribution = full || args.includes('--distribution');
  const live = full || args.includes('--live');
  const git = async (...values) => (await exec('git', values, { cwd: root })).stdout.trim();
  const commit = await git('rev-parse', 'HEAD');
  if (full && await git('status', '--porcelain')) throw Error('完整发布测试要求工作区干净；先整理并提交候选，再运行 --full');
  if (distribution && process.env.MEMWEAVE_DISTRIBUTION_REF && process.env.MEMWEAVE_DISTRIBUTION_REF !== commit)
    throw Error('MEMWEAVE_DISTRIBUTION_REF 必须等于当前候选完整 HEAD，不能测试其他提交');
  const pkg = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
  const host = JSON.parse(await readFile(new URL('../node_modules/@earendil-works/pi-coding-agent/package.json', import.meta.url), 'utf8'));
  console.log(JSON.stringify({ candidate: commit, package: `${pkg.name}@${pkg.version}`, node: process.version, pi: host.version, full, distribution, live }));
  async function step(label, values) {
    console.log(`\n[发布测试] ${label}`);
    await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, values, { cwd: root, stdio: 'inherit',
        env: { ...process.env, MEMWEAVE_DISTRIBUTION_REF: commit } });
      const interrupt = () => child.kill('SIGINT');
      const terminate = () => child.kill('SIGTERM');
      process.on('SIGINT', interrupt); process.on('SIGTERM', terminate);
      child.once('error', reject);
      child.once('close', (code, signal) => {
        process.off('SIGINT', interrupt); process.off('SIGTERM', terminate);
        if (code === 0) resolve();
        else reject(Error(`${label}失败（${signal ?? `退出码 ${code}`}），停止后续阶段`));
      });
    });
  }
  await step('资源/类型/单元/实际 Pi 集成回归', [npm, 'run', 'check']);
  await step('构建', [npm, 'run', 'build']);
  await step('发布入口与候选归档功能验收', ['--test', '发布测试/入口.test.mjs', '发布测试/产物.test.mjs']);
  if (distribution) await step('npm/Git 分发、升级与卸载', [npm, 'run', 'test:distribution']);
  if (live) await step('真实 DeepSeek 产物冒烟', ['--test', 'tests/live/release.test.ts']);
  if (full && (await git('rev-parse', 'HEAD') !== commit || await git('status', '--porcelain')))
    throw Error('验收期间候选 commit 或工作区发生变化，结果不能用于发布');
  console.log(full
    ? '\n完整自动发布测试通过；继续核对发布.md中的其他宿主、真实终端与专项记录。尚未执行发布。'
    : '\n本次选择的回归阶段通过；未执行完整发布门槛，不能据此发布。');
}

main().catch((error) => { console.error(`[发布测试] ${error.message}`); process.exitCode = 1; });
