import fs from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

export async function writeSnapshot(file, value) {
  if (!(await fs.stat(path.dirname(file))).isDirectory()) throw Error('STATE_DIRECTORY_MISSING');
  const tmp = `${file}.${randomUUID()}.tmp`;
  let handle;
  try {
    handle = await fs.open(tmp, 'wx', 0o600);
    await handle.writeFile(JSON.stringify(value));
    await handle.sync();
    await handle.close(); handle = null;
    await fs.rename(tmp, file);
  } finally {
    if (handle) await handle.close();
    await fs.rm(tmp, { force: true });
  }
}

export class AtomicStateStore {
  constructor({ file, initial, writeSnapshot: writer = writeSnapshot }) {
    this.file = file; this.value = structuredClone(initial); this.writer = writer;
    this.persisted = existsSync(file); this.failed = null; this.tail = Promise.resolve();
  }
  current() { return structuredClone(this.value); }
  transact(mutator) {
    const run = async () => {
      if (this.failed) throw this.failed;
      const candidate = structuredClone(this.value);
      const replacement = await mutator(candidate);
      const next = replacement === undefined ? candidate : replacement;
      try {
        if (this.persisted && JSON.stringify(next) === JSON.stringify(this.value)) {
          await fs.stat(this.file);
          return this.current();
        }
        await this.writer(this.file, next);
        this.value = structuredClone(next); this.persisted = true;
        return this.current();
      } catch (error) { this.failed = error; throw error; }
    };
    this.tail = this.tail.then(run, run);
    void this.tail.catch(() => {});
    return this.tail;
  }
  async flush() { await this.tail; }
  async recover() {
    await this.tail.catch(() => {});
    this.value = JSON.parse(await fs.readFile(this.file, 'utf8'));
    this.persisted = true; this.failed = null; this.tail = Promise.resolve();
    return this.current();
  }
}
