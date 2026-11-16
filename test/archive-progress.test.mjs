import test from 'node:test';import assert from 'node:assert/strict';
import {ArchiveProgress} from '../src/archive-progress.mjs';
test('progress groups successful work and acknowledges only after commit',async()=>{
 let writes=0,release;const gate=new Promise(r=>release=r);
 const p=new ArchiveProgress({maxItems:10,maxDelayMs:1000,commit:async()=>{writes++;await gate;}});
 const jobs=Array.from({length:100},(_,i)=>p.complete(String(i),{}));let done=false;void jobs[0].then(()=>done=true);
 await new Promise(r=>setImmediate(r));assert.equal(done,false);release();await p.flush();await Promise.all(jobs);assert.ok(writes<=10);
});
test('timer commits short batches and a failed commit rejects all affected completions',async()=>{
 const p=new ArchiveProgress({maxDelayMs:1,commit:async()=>{throw Error('DISK_FULL')}});
 await assert.rejects(p.complete('one',{}),/DISK_FULL/);
});
