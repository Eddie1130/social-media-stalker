import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { initializeSettings } from '../src/telegram-settings.mjs';
import { PersonalDelivery } from '../src/telegram-delivery.mjs';
import { notificationPublisher } from '../src/telegram-events.mjs';
import { tikTokContentPlan } from '../src/tiktok-content-files.mjs';
function fixture(t) {
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'telegram-album-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const settings=initializeSettings({IG_CONTROL_DIR:dir,TELEGRAM_CHAT_ID:'100',IG_TARGET_USERNAMES:'alice'},1000);
 const args={dir,stateDir:dir,settings:()=>settings};return {dir,settings,args,delivery:new PersonalDelivery(args)};
}
const album=()=>({version:1,type:'media',username:'alice',target:'99',at:3000,publishedAt:2000,kind:'post',id:'post:7:album:71-72',ids:['post:7:71','post:7:72'],method:'sendMediaGroup',body:{media:[{type:'photo',media:'https://s.cdninstagram.com/a.jpg',caption:'one caption'},{type:'video',media:'https://s.cdninstagram.com/b.mp4',supports_streaming:true}]}});
test('publisher to personal delivery keeps a mixed carousel together, refreshes URLs, retries and deduplicates members',async t=>{
 const f=fixture(t),event=album(),publisher=notificationPublisher({IG_STATE_DIR:f.dir});
 publisher.media(event.username,event.target,event.method,event.body,{id:event.id,ids:event.ids,kind:event.kind,detectedAt:event.at,publishedAt:event.publishedAt});
 const file=fs.readdirSync(path.join(f.dir,'telegram-events'))[0];f.delivery.ingest(JSON.parse(fs.readFileSync(path.join(f.dir,'telegram-events',file))));
 fs.writeFileSync(path.join(f.dir,'catalog-99.json'),JSON.stringify({assets:{'post:7:72':{mediaUrl:'https://s.cdninstagram.com/fresh.mp4'}}}));
 const calls=[];await f.delivery.drain({call:async(method,body)=>{calls.push({method,body});throw Error('TELEGRAM_ERROR_429');}});
 assert.equal(calls.length,1);assert.equal(calls[0].method,'sendMediaGroup');assert.equal(calls[0].body.media.length,2);
 assert.equal(calls[0].body.media[1].media,'https://s.cdninstagram.com/fresh.mp4');assert.equal(calls[0].body.media[1].caption,undefined);
 const delivery=new PersonalDelivery(f.args);for(const task of Object.values(delivery.state.pending))task.retryAt=0;
 await delivery.drain({call:async(method,body)=>calls.push({method,body})});
 delivery.ingest(event);
 delivery.ingest({...event,id:event.ids[0],ids:undefined,method:'sendPhoto',body:{photo:event.body.media[0].media,caption:'old single'}});
 await delivery.drain({call:async()=>assert.fail('duplicate post')});assert.equal(calls.length,2);
});
test('album replaces legacy pending singles and legacy events cannot split a pending album',async t=>{
 const f=fixture(t),event=album(),single={...event,id:event.ids[0],ids:undefined,method:'sendPhoto',body:{photo:event.body.media[0].media,caption:'old'}};
 f.delivery.ingest(single);f.delivery.ingest(event);f.delivery.ingest(single);
 assert.equal(Object.keys(f.delivery.state.pending).length,1);
 const calls=[];await f.delivery.drain({call:async(method,body)=>calls.push({method,body})});assert.equal(calls.length,1);assert.equal(calls[0].method,'sendMediaGroup');
});
test('partially acknowledged legacy carousel sends only remaining media without repeating caption',async t=>{
 const f=fixture(t),event=album();f.delivery.ingest({...event,id:event.ids[0],ids:undefined,method:'sendPhoto',body:{photo:event.body.media[0].media,caption:'old'}});
 await f.delivery.drain({call:async()=>{}});f.delivery.ingest(event);
 const calls=[];await f.delivery.drain({call:async(method,body)=>calls.push({method,body})});
 assert.equal(calls.length,1);assert.equal(calls[0].method,'sendVideo');assert.equal(calls[0].body.caption,undefined);
});
test('album validation rejects invalid members and preserves subscription controls',t=>{
 const f=fixture(t);
 for(const mutate of [e=>e.body.media[1].media='http://127.0.0.1/private',e=>e.body.media[1].type='document',e=>e.ids.pop(),e=>e.ids[1]=e.ids[0],e=>e.body.media.push(...Array(9).fill(e.body.media[0]))]) {
  const event=album();mutate(event);assert.throws(()=>f.delivery.ingest(event),/MEDIA_INVALID/);
 }
 f.settings.users['100'].targets.alice.notifications.post.enabled=false;f.delivery.ingest(album());assert.equal(Object.keys(f.delivery.state.pending).length,0);
});
test('TikTok posts spanning multiple albums attach their caption only once',()=>{
 const actions=tikTokContentPlan({text:'old',mediaCaption:'once',files:Array.from({length:12},(_,i)=>`${i}.mp4`)});
 assert.deepEqual(actions.map(a=>a.method),['sendMediaGroup','sendMediaGroup']);
 assert.equal(actions[0].body.media[0].caption,'once');assert.ok(actions[1].body.media.every(m=>m.caption===undefined));
});
test('per-recipient multi-album retries preserve post order without blocking another post',async t=>{
 const f=fixture(t),first={...album(),postId:'7',postOrder:1},second={...album(),id:'post:7:album:73-74',ids:['post:7:73','post:7:74'],postId:'7',postOrder:3};
 for(const m of second.body.media)delete m.caption;
 f.delivery.ingest(second);f.delivery.ingest(first);
 const other={...album(),id:'post:8:album:81-82',ids:['post:8:81','post:8:82'],postId:'8',postOrder:1};f.delivery.ingest(other);
 const calls=[];await f.delivery.drain({call:async(method,body)=>{calls.push(body);if(calls.length===1)throw Error('TELEGRAM_ERROR_429');}});
 assert.equal(calls.length,2);assert.equal(calls[0].media[0].caption,'one caption');
 const delivery=new PersonalDelivery(f.args),retry=[];
 await delivery.drain({call:async()=>assert.fail('later chunk must wait for retry')});
 for(const task of Object.values(delivery.state.pending))task.retryAt=0;
 await delivery.drain({call:async(method,body)=>retry.push(body)});
 assert.equal(retry.length,2);assert.equal(retry[0].media[0].caption,'one caption');assert.equal(retry[1].media[0].caption,undefined);
});

test('duplicate events do not rewrite identical receipts; failed changed writes retry',t=>{
 const f=fixture(t),event=album();f.delivery.ingest(event);
 const before=fs.readFileSync(f.delivery.file,'utf8'),sync=fs.fsyncSync;let writes=0;
 try{
  fs.fsyncSync=(...args)=>{writes++;return sync(...args);};
  f.delivery.ingest(event);
  assert.equal(writes,0);assert.equal(fs.readFileSync(f.delivery.file,'utf8'),before);
  f.delivery.state.summaries['100']='2026-11-16';
  fs.fsyncSync=()=>{throw Error('DISK_FAILURE');};
  assert.throws(()=>f.delivery.persist(),/DISK_FAILURE/);
  fs.fsyncSync=(...args)=>{writes++;return sync(...args);};f.delivery.persist();
  assert.equal(writes,1);
  assert.equal(JSON.parse(fs.readFileSync(f.delivery.file,'utf8')).summaries['100'],'2026-11-16');
 }finally{fs.fsyncSync=sync;}
});
