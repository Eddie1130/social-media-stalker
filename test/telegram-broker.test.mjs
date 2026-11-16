import test from 'node:test';import assert from 'node:assert/strict';
import {validateBrokerRequest,eligibilityFingerprint} from '../src/telegram-delivery-broker.mjs';
test('broker rejects polling, unknown recipients, and oversized IPC bodies',()=>{
 const s={ownerId:'100',allowedIds:['100'],users:{100:{targets:{}}}};
 assert.throws(()=>validateBrokerRequest({method:'getUpdates',body:{}},s));
 assert.throws(()=>validateBrokerRequest({method:'sendMessage',body:{chat_id:'200'}},s));
 assert.throws(()=>validateBrokerRequest({method:'sendMessage',body:{chat_id:'100',text:'x'.repeat(3e6)}},s));
 assert.doesNotThrow(()=>validateBrokerRequest({method:'sendMessage',body:{chat_id:'100',text:'hi'}},s));
 const first=eligibilityFingerprint(s,'100');s.users['200']={};assert.equal(eligibilityFingerprint(s,'100'),first);
 s.users['100'].targets.alice={generation:'new'};assert.notEqual(eligibilityFingerprint(s,'100'),first);
});

import {EventEmitter} from 'node:events';import {DeliveryBroker} from '../src/telegram-delivery-broker.mjs';
class FakeChild extends EventEmitter {
 constructor(){super();this.connected=true;this.exitCode=0;this.sent=[];}
 send(m,cb){this.sent.push(m);if(m.type==='prepare')setImmediate(()=>this.emit('message',{type:'prepared',requestId:m.requestId,fingerprint:m.fingerprint}));cb?.();}
}
test('broker checkpoints preparation before HTTP and rejects a revoked recipient',async()=>{
 const child=new FakeChild();let sent=0;
 const settings={ownerId:'100',allowedIds:['100'],users:{100:{}}};
 const client={rate:{retryAt:0},call:async(_m,_b,o)=>{await o.prepareRequest();o.beforeSend();sent++;return {message_id:1};}};
 const broker=new DeliveryBroker({client,settings:()=>settings,child});
 await broker.message({type:'request',requestId:'11111111-1111-1111-1111-111111111111',method:'sendMessage',body:{chat_id:'100',text:'test'}});
 assert.equal(sent,1);assert.ok(child.sent.some(x=>x.type==='result'&&x.result?.message_id===1));
 client.call=async(_m,_b,o)=>{await o.prepareRequest();settings.allowedIds=[];o.beforeSend();sent++;};
 await broker.message({type:'request',requestId:'22222222-2222-2222-2222-222222222222',method:'sendMessage',body:{chat_id:'100',text:'test'}});
 assert.equal(sent,1);assert.ok(child.sent.some(x=>x.type==='result'&&x.error));await broker.stop();
});

import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {pathToFileURL} from 'node:url';
import {validateBrokerFiles} from '../src/telegram-delivery-broker.mjs';
test('broker cannot ask the Local API to read files outside approved media roots',async t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'broker-files-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));fs.writeFileSync(path.join(root,'clip.mp4'),'media');
 await validateBrokerFiles({video:pathToFileURL(path.join(root,'clip.mp4')).href},[root]);
 await assert.rejects(validateBrokerFiles({video:'file:///etc/passwd'},[root]));
 fs.symlinkSync('/etc/passwd',path.join(root,'escape.mp4'));await assert.rejects(validateBrokerFiles({video:pathToFileURL(path.join(root,'escape.mp4')).href},[root]));
});

import {deliveryWorkerEnv,validAttachmentName} from '../src/telegram-delivery-broker.mjs';
import {spawnSync} from 'node:child_process';
test('real child inherits Local API 2GB limit without receiving the bot token',()=>{
 const script=`import {albumPlan} from ${JSON.stringify(new URL('../src/manual-delivery.mjs',import.meta.url).href)}; console.log(JSON.stringify({oversized:albumPlan([{bytes:100000000,mediaType:2}]).oversized.length,token:!!process.env.TELEGRAM_BOT_TOKEN}));`;
 const result=spawnSync(process.execPath,['--input-type=module','-e',script],{env:deliveryWorkerEnv({PATH:process.env.PATH,TELEGRAM_BOT_TOKEN:'secret'},'http://local:8081'),encoding:'utf8'});
 assert.equal(result.status,0,result.stderr);assert.deepEqual(JSON.parse(result.stdout),{oversized:0,token:false});
 for(const name of ['media0','media9','thumb0','cover9','thumbnail'])assert.equal(validAttachmentName(name),true);
 for(const name of ['media10','../secret','token'])assert.equal(validAttachmentName(name),false);
});
