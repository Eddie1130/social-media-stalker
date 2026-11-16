import test from 'node:test';
import assert from 'node:assert/strict';
import { applyUpdate } from '../src/telegram-menu.mjs';
const setup = () => ({ ownerId: '100', allowedIds: ['100', '200'], offset: 0, replies: {}, users: { '100': { targets: {} }, '200': { targets: {} } } });
const click = (data, id = '100') => ({ update_id: 1, callback_query: { id: 'cb', data, from: { id }, message: { message_id: 4, chat: { id, type: 'private' } } } });
test('status shows all monitors button only for owner', () => {
  for (const id of ['100', '200']) {
    const s = setup(); applyUpdate(s, click('status', id));
    assert.equal(JSON.stringify(s.replies['reply:1']).includes('admin-status:0'), id === '100');
  }
});
test('forged admin callback never invokes global reader', () => {
  const s = setup(); const describe = () => ''; describe.admin = () => { throw Error('unauthorized'); };
  applyUpdate(s, click('admin-status:0', '200'), 1, describe);
  assert.doesNotMatch(s.replies['reply:1'].body.text, /secret/);
});
test('owner callback renders requested global page', () => {
  const s = setup(); const describe = () => ''; describe.admin = page => ({ text: `global page ${page}`, reply_markup: { inline_keyboard: [] } });
  applyUpdate(s, click('admin-status:2'), 1, describe);
  assert.equal(s.replies['reply:1'].body.text, 'global page 2');
});

import { adminStatus } from '../src/admin-status.mjs';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
test('global status deduplicates subscriptions and paginates all accounts', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'admin-status-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const s = setup();
  s.users['100'].xTargets = { alice: {} };
  s.users['200'].xTargets = Object.fromEntries(['alice', ...Array.from({ length: 13 }, (_, i) => `user${i}`)].map(n => [n, {}]));
  fs.mkdirSync(path.join(dir, 'x'));
  fs.writeFileSync(path.join(dir, 'x/health.json'), JSON.stringify({ at: 1000, targets: [{ username: 'alice', pending: 7 }] }));
  const first = adminStatus(s, dir, 0, 1000);
  assert.match(first.text, /14 個帳號 · 待下載 7/);
  assert.match(first.text, /@alice · 正常\n待下載：7/);
  assert.match(first.text, /第 1\/2 頁/);
  assert.match(adminStatus(s, dir, 999, 1000).text, /第 2\/2 頁/);
  assert.ok(first.text.length < 4096);
});
test('empty global status is usable', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'admin-empty-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  assert.match(adminStatus(setup(), dir).text, /尚未新增帳號/);
});
test('revoked users do not count as active monitors', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'admin-revoked-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const s = setup(); s.allowedIds = ['100']; s.users['200'].targets = { removed: {} };
  assert.doesNotMatch(adminStatus(s, dir).text, /@removed/);
});
