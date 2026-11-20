import test from 'node:test';import assert from 'node:assert/strict';import {platformStatus} from '../src/platform-status.mjs';
test('fresh heartbeat does not hide old TikTok content or transient failures',()=>{
 const now=1000000,user={tiktokTargets:{alice:{notifications:{post:{enabled:true}}}}};
 let post={phase:'監看中',failures:0,consecutiveFailures:0,lastSuccess:now-600000};
 const read=f=>f.endsWith('catalog/health.json')?{at:now,targets:{alice:{post}}}:{at:now,targets:{alice:{phase:'監看中'}}};
 assert.match(platformStatus(user,'tt','/state',read,now).accounts.alice,/更新較慢/);
 post={phase:'監看中',failures:0,consecutiveFailures:1,lastSuccess:now};
 assert.match(platformStatus(user,'tt','/state',read,now).accounts.alice,/暫時失敗/);
});
test('legacy Instagram archives complete without a history request timestamp', () => {
 const now=1000000,user={targets:{alice:{monitorOnly:true}}};
 const catalog={posts:{baseline:true,backfill:false},highlights:{baseline:true,backfill:false},assets:{a:{archiveDone:true}},captions:{p:{hash:'empty',savedHash:'empty'}}};
 const read=f=>f.endsWith('health.json')?{at:now,targets:[{username:'alice',target:'123'}]}:catalog;
 assert.equal(platformStatus(user,'ig','/state',read,now).archived.alice,true);
 catalog.assets.a.archiveDone=false;
 assert.equal(platformStatus(user,'ig','/state',read,now).archived.alice,false);
});
