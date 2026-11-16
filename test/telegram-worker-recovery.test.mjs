import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {PersonalDelivery} from '../src/telegram-delivery.mjs';
import {initializeSettings} from '../src/telegram-settings.mjs';
function setup(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'worker-recovery-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));const settings=initializeSettings({IG_CONTROL_DIR:dir,TELEGRAM_CHAT_ID:'100'});const d=new PersonalDelivery({dir,stateDir:dir,settings:()=>settings});const key='summary:test';const day=new Date(Date.now()+8*3600000).toISOString().slice(0,10);settings.users['100'].daily=true;d.state.pending[key]={userId:'100',type:'summary',day,method:'sendMessage',body:{chat_id:'100',text:'summary'},at:Date.now(),failures:0,retryAt:0};d.persist();return {dir,settings,d,key};}
test('queued personal task rechecks eligibility after worker settings update',async t=>{
 const f=setup(t);let sent=0;
 await f.d.drain({call:async(_m,_b,o)=>{f.settings.users['100'].daily=false;o.beforeRequest();sent++;}});
 assert.equal(sent,0);assert.equal(Object.keys(f.d.state.pending).length,0);
});
test('worker restart never resends personal task whose HTTP result was lost',async t=>{
 const f=setup(t);let marked=false;
 await f.d.drain({call:async(_m,_b,o)=>{o.beforeRequest();const onDisk=JSON.parse(fs.readFileSync(f.d.file));marked=onDisk.pending[f.key].inflight===true;throw Error('TELEGRAM_NETWORK_OR_RESPONSE_ERROR');}});
 assert.equal(marked,true);
 const restarted=new PersonalDelivery({dir:f.dir,stateDir:f.dir,settings:()=>f.settings});
 await restarted.drain({call:()=>assert.fail('uncertain task must not resend')});
 assert.equal(restarted.state.pending[f.key].uncertain,true);
});
test('daily with no new summary does not write state on every dispatch loop',()=>{
 let writes=0;PersonalDelivery.prototype.daily.call({state:{summaries:{}},settings:()=>({allowedIds:['100'],users:{100:{daily:false}}}),persist:()=>writes++},Date.parse('2026-11-15T12:00:00Z'),()=> '');assert.equal(writes,0);
});
