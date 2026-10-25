// Local allocation/render microbenchmark only; no provider calls or user data.
import { execFileSync } from 'node:child_process';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { performance } from 'node:perf_hooks';
import { allocate } from '../../src/window/budget.ts';
import { conservativeCounter, deepseekCounter } from '../../src/window/tokens.ts';

const repository = fileURLToPath(new URL('../../', import.meta.url));
const root = await mkdtemp(join(tmpdir(), 'memweave-elastic-perf-'));
try {
  let source = execFileSync('git', ['show', 'c19448d:src/window/budget.ts'], { cwd: repository, encoding: 'utf8' });
  for (const name of ['tokens', 'policy']) source = source.replace(`"./${name}.ts"`, JSON.stringify(new URL(`../../src/window/${name}.ts`, import.meta.url).href));
  const oldFile = join(root, 'old-budget.ts');
  await writeFile(oldFile, source);
  const old = await import(pathToFileURL(oldFile).href);
  const text = 'Budget preparation with Unicode 正文和工具日志😀 and native call pairs.\n';
  // Explicit groups isolate this algorithm; this is not a native Session/event-index benchmark.
  const messages = Array.from({ length: 400 }, (_, i) => ({
    message: { role: 'user', content: (text + String(i) + '\n').repeat(45), timestamp: i },
    head: `[U${i + 1}]`, exempt: false, event: String(Math.floor(i / 4)),
    group: i >= 388 ? 'current' : i >= 376 ? 'recent' : 'older',
  }));
  messages.push({ message: { role: 'user', content: 'Current task input', timestamp: 401 },
    head: '[U401]', exempt: true, event: 'latest', group: 'recent' });
  for (const counter of [conservativeCounter, await deepseekCounter()]) {
    const input = { limit: 629145, capacity: 1048576, system: 20000, state: 10000,
      output: 62914, reminder: 2048, messages, imageCost: () => 0, counter };
    const rows = { before: [], after: [] };
    for (let trial = 0; trial < 6; trial++) for (const which of ['before', 'after']) {
      const start = performance.now();
      if (which === 'before') {
        const budget = old.allocate(input);
        messages.map(item => old.renderMessage(item.message, item.head, budget.Q, item.exempt, counter));
      } else {
        const budget = allocate(input);
        if (budget.rendered.length !== messages.length) throw Error('Missing rendered messages');
      }
      if (trial) rows[which].push(performance.now() - start);
    }
    const stats = Object.fromEntries(Object.entries(rows).map(([key, values]) => {
      values.sort((a, b) => a - b);
      return [key, { median_ms: Math.round(values[2] * 10) / 10, max_ms: Math.round(values.at(-1) * 10) / 10 }];
    }));
    console.log(JSON.stringify({ counter: counter.estimator, messages: messages.length,
      utf8_bytes: messages.reduce((n, item) => n + Buffer.byteLength(item.message.content), 0), runs: 5, ...stats }));
  }
} finally {
  await rm(root, { recursive: true, force: true });
}
