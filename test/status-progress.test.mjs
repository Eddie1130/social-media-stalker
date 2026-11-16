import test from 'node:test';
import assert from 'node:assert/strict';
import { platformStatus } from '../src/platform-status.mjs';
import { platformMenu } from '../src/platform-menu.mjs';
const now = 10000;
function overview(platform, target, catalog, at = now) {
  const key = { ig: 'targets', x: 'xTargets', tt: 'tiktokTargets' }[platform];
  const user = { [key]: { alice: {} } };
  const read = (file, fallback) => file.endsWith('catalog-123.json') ? catalog : file.endsWith('health.json') ? { at, targets: platform === 'tt' ? { alice: target } : [target] } : fallback;
  return { user, status: platformStatus(user, platform, '', read, now) };
}
test('IG progress distinguishes discovery, downloading and complete in user views', () => {
  const catalog = { posts: { baseline: false }, highlights: { baseline: true }, assets: { a: { archiveDone: false } } };
  const get = () => overview('ig', { username: 'alice', target: '123' }, catalog);
  assert.match(get().status.text, /仍在搜尋/);
  catalog.posts.baseline = true;
  let o = get(); assert.match(o.status.text, /搜尋完成，下載媒體中/);
  assert.match(platformMenu(o.user, 'ig', 0, o.status).text, /搜尋完成，下載媒體中/);
  catalog.assets.a.archiveDone = true;
  assert.match(get().status.text, /已完成，持續監控新內容/);
  assert.doesNotMatch(get().status.text, /待下載：0/);
  assert.doesNotMatch(overview('ig', { username: 'alice', target: '123' }, catalog, 0).status.text, /已完成，持續監控/);
});
test('TikTok unfinished streams and unresolved records never claim completion', () => {
  assert.match(overview('tt', { post: { baseline: false } }).status.text, /仍在搜尋/);
  assert.match(overview('tt', { post: { baseline: true, pending: 2 } }).status.text, /搜尋完成，下載媒體中/);
  assert.match(overview('tt', { post: { baseline: true } }).status.text, /已完成，持續監控/);
  assert.doesNotMatch(overview('tt', { post: { baseline: true, unresolved: 1 } }).status.text, /已完成，持續監控/);
});
test('X successful polling distinguishes download queue and monitoring', () => {
  assert.match(overview('x', { username: 'alice', lastSuccess: 1000, pending: 2 }).status.text, /搜尋完成，下載媒體中/);
  assert.match(overview('x', { username: 'alice', lastSuccess: 1000 }).status.text, /已完成，持續監控/);
  assert.doesNotMatch(overview('x', { username: 'alice' }).status.text, /已完成，持續監控/);
});
