import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {SettingsStore} from '../src/telegram-state-store.mjs';import {initializeSettings} from '../src/telegram-settings.mjs';
test('settings transactions keep updates and replies across asynchronous commits',async t=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'settings-store-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
 const env={IG_CONTROL_DIR:dir,TELEGRAM_CHAT_ID:'100'};const initial=initializeSettings(env);const store=new SettingsStore({file:path.join(dir,'settings.json'),initial});
 await Promise.all([store.transact(s=>{s.offset=10}),store.transact(s=>{s.users['100'].daily=true})]);
 assert.equal(store.current().offset,10);assert.equal(store.current().users['100'].daily,true);
 await assert.rejects(store.transact(s=>{s.offset=-1}));assert.equal(store.current().offset,10);
});
