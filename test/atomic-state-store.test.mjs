import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import { AtomicStateStore } from '../src/atomic-state-store.mjs';
function fixture(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'atomic-store-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));return path.join(dir,'state.json');}
test('concurrent transactions serialize, publish after durable write, and skip identical data',async t=>{
 const file=fixture(t);let writes=0;const store=new AtomicStateStore({file,initial:{n:0},writeSnapshot:async(_f,s)=>{writes++;await new Promise(r=>setImmediate(r));fs.writeFileSync(file,JSON.stringify(s));}});
 const a=store.transact(s=>{s.n++});assert.equal(store.current().n,0);const b=store.transact(s=>{s.n++});await Promise.all([a,b]);
 assert.equal(store.current().n,2);await store.transact(()=>{});assert.equal(writes,2);
});
test('failed commit rejects queued mutations and recover reloads last durable snapshot',async t=>{
 const file=fixture(t);fs.writeFileSync(file,'{"n":0}');let fail=true;
 const store=new AtomicStateStore({file,initial:{n:0},writeSnapshot:async(_f,s)=>{if(fail)throw Error('DISK_FULL');fs.writeFileSync(file,JSON.stringify(s));}});
 await assert.rejects(store.transact(s=>{s.n++}),/DISK_FULL/);assert.equal(store.current().n,0);await assert.rejects(store.transact(s=>{s.n++}));
 fail=false;await store.recover();await store.transact(s=>{s.n++});assert.equal(store.current().n,1);
});
test('real atomic writer preserves old state on invalid destination and creates durable state',async t=>{
 const file=fixture(t);const store=new AtomicStateStore({file,initial:{n:0}});await store.transact(s=>{s.n++});assert.deepEqual(JSON.parse(fs.readFileSync(file)),{n:1});assert.equal(fs.statSync(file).mode&0o777,0o600);
});
test('rejected business mutation does not poison later valid transactions',async t=>{
 const file=fixture(t),store=new AtomicStateStore({file,initial:{n:0}});
 await assert.rejects(store.transact(()=>{throw Error('EXPORT_INVALID_REPORT')}));
 await store.transact(s=>{s.n=1;});assert.equal(store.current().n,1);
});
