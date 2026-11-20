import test from 'node:test';
import assert from 'node:assert/strict';
import { applyUpdate } from '../src/telegram-menu.mjs';
import { completedHistoryPanels } from '../src/telegram-control.mjs';
import { subscription } from '../src/telegram-settings.mjs';
import { tikTokSubscription } from '../src/tiktok-settings.mjs';
import { xSubscription } from '../src/x-settings.mjs';

for (const [platform, key, create, prefix] of [
  ['ig', 'targets', subscription, ''], ['tt', 'tiktokTargets', tikTokSubscription, 'tt:'], ['x', 'xTargets', xSubscription, 'x:'],
]) test(platform + ' replaces the history button and ignores old callbacks after archival', () => {
  const sub = create(1000), user = { [key]: { alice: sub } };
  const settings = { offset: 0, ownerId: '1', allowedIds: ['1'], users: { '1': user }, replies: {} };
  let archived = false;
  const describe = { platform: () => ({ archived: { alice: archived } }) };
  function click(n, data) {
    applyUpdate(settings, { update_id: n, callback_query: { id: String(n), data, from: { id: 1 },
      message: { message_id: 77, chat: { type: 'private', id: 1 } } } }, 2000, describe);
    return settings.replies['reply:' + n].body;
  }
  const action = prefix + 'history:alice:' + sub.generation.slice(0, 8);
  assert.ok(click(1, prefix + 'account:alice').reply_markup.inline_keyboard.flat().some(b => b.callback_data === action));
  click(2, action);
  assert.deepEqual(completedHistoryPanels(settings, describe), []);
  archived = true;
  assert.match(completedHistoryPanels(settings, describe)[0].body.text, /已封存/);
  const account = click(3, prefix + 'account:alice');
  assert.match(account.text, /已封存/);
  assert.ok(!account.reply_markup.inline_keyboard.flat().some(b => b.callback_data === action));
  assert.match(click(4, action).text, /已封存/);
});
