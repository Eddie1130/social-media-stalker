import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { TelegramClient } from '../src/telegram-client.mjs';
import { flushReplies } from '../src/telegram-replies.mjs';

function fixture(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'telegram-latency-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

test('callback acknowledgement does not wait behind reserved media slots', async t => {
  const dir = fixture(t);
  let now = 1000;
  t.mock.method(Date, 'now', () => now);
  const sleepers = [];
  const calls = [];
  const client = new TelegramClient({ token: '1:abc', dir,
    sleep: ms => ms > 0 ? new Promise(resolve => sleepers.push({ ms, resolve })) : Promise.resolve(),
    fetchImpl: async url => { calls.push(url.split('/').at(-1)); return { ok: true, json: async () => ({ ok: true, result: true }) }; },
  });
  const media = Array.from({ length: 7 }, () => client.call('sendVideo', { chat_id: '100' }));
  await new Promise(resolve => setImmediate(resolve));
  const ack = client.call('answerCallbackQuery', { callback_query_id: 'test' });
  await new Promise(resolve => setImmediate(resolve));
  now += 40;
  for (const sleeper of sleepers.splice(0)) { if (sleeper.ms <= 40) sleeper.resolve(); else sleepers.push(sleeper); }
  await new Promise(resolve => setImmediate(resolve));
  const prompt = calls.includes('answerCallbackQuery');
  // Release every pending call even when the old implementation fails.
  for (let i = 0; i < 20; i++) {
    now += 1100;
    for (const sleeper of sleepers.splice(0)) sleeper.resolve();
    await new Promise(resolve => setImmediate(resolve));
  }
  await Promise.all([...media, ack]);
  assert.equal(prompt, true, 'callback must get the next global slot, not wait 6+ seconds for media reservations');
});

test('one menu click checkpoints reply removals once instead of fsync per API call', async () => {
  const settings = { allowedIds: ['100'], users: {}, replies: {
    ack: { method: 'answerCallbackQuery', body: { callback_query_id: 'a' }, userId: '100', at: 1 },
    menu: { method: 'editMessageText', body: { chat_id: '100', message_id: 42, text: 'menu' }, userId: '100', at: 1 },
  } };
  let writes = 0;
  const calls = [];
  await flushReplies(settings, { call: async method => calls.push(method) }, () => writes++);
  assert.deepEqual(calls, ['answerCallbackQuery', 'editMessageText']);
  assert.equal(writes, 1);
  assert.deepEqual(settings.replies, {});
});

test('menu edit gets next chat slot while background media keeps chat spacing', async t => {
  const dir = fixture(t);
  let now = 1000;
  t.mock.method(Date, 'now', () => now);
  const sleepers = [], calls = [];
  const client = new TelegramClient({ token: '1:abc', dir,
    sleep: ms => new Promise(resolve => sleepers.push({ ms, resolve })),
    fetchImpl: async (url, options) => { calls.push({ method: url.split('/').at(-1), at: now, chat: JSON.parse(options.body).chat_id }); return { ok: true, json: async () => ({ ok: true, result: true }) }; },
  });
  const tasks = Array.from({ length: 4 }, () => client.call('sendVideo', { chat_id: '100' }));
  await new Promise(resolve => setImmediate(resolve));
  tasks.push(client.call('editMessageText', { chat_id: '100', message_id: 42 }, { priority: true }));
  await new Promise(resolve => setImmediate(resolve));
  for (let i = 0; i < 10; i++) {
    now += 1100;
    for (const sleeper of sleepers.splice(0)) sleeper.resolve();
    await new Promise(resolve => setImmediate(resolve));
  }
  await Promise.all(tasks);
  assert.deepEqual(calls.slice(0, 2).map(c => c.method), ['sendVideo', 'editMessageText']);
  for (let i = 1; i < calls.length; i++) assert.ok(calls[i].at - calls[i - 1].at >= 1100);
});

test('a blocked media chat does not delay a different chat', async t => {
  const dir = fixture(t);
  let now = 1000;
  t.mock.method(Date, 'now', () => now);
  const sleepers = [], calls = [];
  const client = new TelegramClient({ token: '1:abc', dir,
    sleep: ms => new Promise(resolve => sleepers.push({ ms, resolve })),
    fetchImpl: async (_url, options) => { calls.push(JSON.parse(options.body).chat_id); return { ok: true, json: async () => ({ ok: true, result: true }) }; },
  });
  const tasks = [client.call('sendVideo', { chat_id: '100' }), client.call('sendVideo', { chat_id: '100' })];
  await new Promise(resolve => setImmediate(resolve));
  tasks.push(client.call('sendMessage', { chat_id: '200' }, { priority: true }));
  await new Promise(resolve => setImmediate(resolve));
  now += 40;
  for (const sleeper of sleepers.splice(0)) { if (sleeper.ms <= 40) sleeper.resolve(); else sleepers.push(sleeper); }
  await new Promise(resolve => setImmediate(resolve));
  const prompt = calls.includes('200');
  now += 1100;
  for (const sleeper of sleepers.splice(0)) sleeper.resolve();
  await new Promise(resolve => setImmediate(resolve));
  await Promise.all(tasks);
  assert.equal(prompt, true);
});

test('abort wakes queued rate waiters without starting another API request', async t => {
  const dir = fixture(t), controller = new AbortController();
  let requests = 0;
  const client = new TelegramClient({ token: '1:abc', dir, signal: controller.signal,
    sleep: () => new Promise(() => {}),
    fetchImpl: async () => { requests++; return { ok: true, json: async () => ({ ok: true, result: true }) }; },
  });
  await client.call('sendVideo', { chat_id: '100' });
  const pending = client.call('sendVideo', { chat_id: '100' });
  const stopped = assert.rejects(pending, /TELEGRAM_STOPPING/);
  controller.abort();
  await stopped;
  assert.equal(requests, 1);
});

test('completed message is checkpointed before sending another message', async () => {
  const settings = { allowedIds: ['100'], replies: {
    a: { method: 'sendMessage', body: { chat_id: '100', text: 'one' }, userId: '100', at: 1 },
    b: { method: 'sendMessage', body: { chat_id: '100', text: 'two' }, userId: '100', at: 2 },
  } };
  const checkpoints = [];
  await flushReplies(settings, { call: async (_method, body) => {
    if (body.text === 'two') assert.deepEqual(checkpoints, [['b']]);
  } }, () => checkpoints.push(Object.keys(settings.replies)));
  assert.deepEqual(checkpoints, [['b'], []]);
});

test('queued priority reply still respects a newly received Telegram flood wait', async t => {
  const dir = fixture(t);
  let now = 1000, requests = 0;
  t.mock.method(Date, 'now', () => now);
  const sleepers = [];
  const client = new TelegramClient({ token: '1:abc', dir,
    sleep: ms => new Promise(resolve => sleepers.push({ ms, resolve })),
    fetchImpl: async () => { requests++; return { ok: true, json: async () => ({ ok: true, result: true }) }; },
  });
  await client.call('sendVideo', { chat_id: '100' });
  const queued = client.call('editMessageText', { chat_id: '100' }, { priority: true });
  const rejected = assert.rejects(queued, /TELEGRAM_RETRY_WAIT/);
  client.rate.retryAt = now + 60000;
  now += 1100;
  for (const sleeper of sleepers.splice(0)) sleeper.resolve();
  await rejected;
  assert.equal(requests, 1);
});
