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
  assert.doesNotMatch(overview('ig', { username: 'alice', target: '123' }, catalog, -200000).status.text, /已完成，持續監控/);
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
test('X unfinished history search and rendering never report all complete', () => {
  for (const phase of ['search', 'rendering']) {
    const read = (file, fallback) => file.endsWith('health.json') ? { at: now, targets: [{ username: 'alice', lastSuccess: 1000 }], historyJobs: [{ username: 'alice', status: phase === 'search' ? 'working' : 'complete', phase, fetchDone: phase !== 'search', reported: false }] } : fallback;
    const status = platformStatus({ xTargets: { alice: {} } }, 'x', '', read, now);
    assert.match(status.text, phase === 'search' ? /仍在搜尋/ : /搜尋完成，媒體處理中/);
    assert.doesNotMatch(status.text, /已完成，持續監控/);
  }
});
test('partially completed X history does not claim complete after archival', () => {
  const read = (file, fallback) => file.endsWith('health.json') ? { at: now, targets: [{ username: 'alice', lastSuccess: 1000 }], historyJobs: [{ username: 'alice', status: 'partial', phase: 'finished', fetchDone: true, reported: true }] } : fallback;
  const status = platformStatus({ xTargets: { alice: {} } }, 'x', '', read, now);
  assert.match(status.text, /等待重試或補查/);
  assert.doesNotMatch(status.text, /已完成，持續監控/);
});
test('IG completed initial discovery distinguishes routine rescans', () => {
  const catalog = { posts: { baseline: true, cursor: 'next-page' }, highlights: { baseline: true, todo: [{ id: '1' }] }, assets: {} };
  const status = overview('ig', { username: 'alice', target: '123' }, catalog).status;
  assert.match(status.text, /首次搜尋已完成，例行檢查新內容/);
  assert.doesNotMatch(status.text, /仍在搜尋新貼文/);
});
test('cancelled historical jobs do not block successful X monitoring', () => {
  const read = (file, fallback) => file.endsWith('health.json') ? { at: now, targets: [{ username: 'alice', lastSuccess: 1000 }], historyJobs: [{ username: 'alice', status: 'cancelled', reported: true }, { username: 'alice', status: 'complete', fetchDone: true, reported: true }] } : fallback;
  const status = platformStatus({ xTargets: { alice: {} } }, 'x', '', read, now);
  assert.match(status.text, /已完成，持續監控新內容/);
  assert.doesNotMatch(status.text, /進度待確認/);
});
