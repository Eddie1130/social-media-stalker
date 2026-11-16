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
