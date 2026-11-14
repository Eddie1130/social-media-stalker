import test from 'node:test';
import assert from 'node:assert/strict';
import { parseTikTokLink } from '../src/tiktok-links.mjs';
test('TikTok content and share links are canonicalized', () => {
  assert.equal(parseTikTokLink('https://www.tiktok.com/@alice/video/123?tracking=1'), 'https://www.tiktok.com/@alice/video/123');
  assert.equal(parseTikTokLink('https://vt.tiktok.com/ABC/'), 'https://vt.tiktok.com/ABC/');
  assert.equal(parseTikTokLink('tiktok.com/@alice/photo/123'), 'https://tiktok.com/@alice/photo/123');
});
test('rejects unrelated hosts, credentials, profiles and insecure URLs', () => {
  for (const url of ['https://tiktok.com.evil.com/@a/video/1', 'https://user@www.tiktok.com/@a/video/1', 'http://www.tiktok.com/@a/video/1', 'https://www.tiktok.com/@alice', 'https://www.tiktok.com:444/@a/video/1']) assert.throws(() => parseTikTokLink(url));
});

import { tikTokContentPlan } from '../src/tiktok-content-files.mjs';
import { contentBody } from '../src/tiktok-content-files.mjs';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

test('manual media resolves for chat requests while old queued events remain readable', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'tt-manual-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  for (const prefix of ['tiktok/manual/alice', 'tiktok/alice']) {
    const file = path.join(root, prefix, 'posts/1/01.mp4');
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, Buffer.alloc(32));
  }
  const event = { username: 'alice', kind: 'post', requestId: '100-1-0', manual: true };
  const action = { body: { video: 'local:tiktok/manual/alice/posts/1/01.mp4' } };
  assert.equal(contentBody(root, event, action).video, 'file://' + fs.realpathSync(path.join(root, 'tiktok/manual/alice/posts/1/01.mp4')));
  assert.throws(() => contentBody(root, { ...event, requestId: undefined }, action), /TIKTOK_FILE_INVALID/);
  assert.throws(() => contentBody(root, { ...event, username: 'bob' }, action), /TIKTOK_FILE_INVALID/);
  const legacy = { body: { video: 'local:tiktok/alice/posts/1/01.mp4' } };
  assert.ok(contentBody(root, { ...event, manual: undefined }, legacy).video);
});
test('manual output places IG-style caption on media without a separate text message', () => {
  const plan = tikTokContentPlan({ text: 'old text', mediaCaption: '@alice\nhttps://www.tiktok.com/@alice/video/123\ncaption', files: ['tiktok/alice/posts/123/01.mp4'] });
  assert.equal(plan.length, 1);
  assert.equal(plan[0].method, 'sendVideo');
  assert.equal(plan[0].body.caption, '@alice\nhttps://www.tiktok.com/@alice/video/123\ncaption');
  const album = tikTokContentPlan({ text: 'old', mediaCaption: '@alice', files: ['a.mp4', 'b.mp4'] });
  assert.equal(album[0].body.media[0].caption, '@alice');
  assert.equal(album[0].body.media[1].caption, undefined);
});
