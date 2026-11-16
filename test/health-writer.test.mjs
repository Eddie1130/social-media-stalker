import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createHealthWriter } from '../src/health-writer.mjs';
import { atomic } from '../src/error-monitor.mjs';
function fixture(t){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'health-writer-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));return path.join(dir,'health.json');}
test('unchanged heartbeats are bounded and meaningful changes are durable immediately',t=>{
 const file=fixture(t),write=createHealthWriter(file);
 assert.equal(write({phase:'running'},{now:1000}),true);
 assert.equal(write({phase:'running',at:2000},{now:2000}),false);
 assert.equal(write({phase:'running'},{now:16000}),true);
 assert.equal(write({phase:'fatal'},{now:16001}),true);
 assert.deepEqual(JSON.parse(fs.readFileSync(file)),{phase:'fatal',at:16001});
});
test('supervisor progress remains bounded while force and issue changes publish immediately',t=>{
 const file=fixture(t),write=createHealthWriter(file,{select:s=>({phase:s.phase,activeIssues:s.activeIssues})});
 write({phase:'waiting',activeIssues:0,workerDeadline:151000},{now:1000});
 for(let now=2000;now<15000;now+=1000)assert.equal(write({phase:'waiting',activeIssues:0,workerDeadline:now+150000,lastEvent:'WAIT'},{now}),false);
 assert.equal(write({phase:'waiting',activeIssues:0,workerDeadline:165000},{now:15000,force:true}),true);
 assert.equal(write({phase:'waiting',activeIssues:1,workerDeadline:165001},{now:15001}),true);
 assert.equal(JSON.parse(fs.readFileSync(file)).activeIssues,1);
});
test('failed writes never advance the heartbeat cache, missing files and clock rollback recover',t=>{
 const file=fixture(t);let fail=true;
 const write=createHealthWriter(file,{writer:(p,v)=>{if(fail)throw Error('DISK_FAILURE');atomic(p,v);}});
 assert.throws(()=>write({phase:'running'},{now:1000}),/DISK_FAILURE/);fail=false;
 assert.equal(write({phase:'running'},{now:1001}),true);
 fail=true;assert.throws(()=>write({phase:'fatal'},{now:1002}),/DISK_FAILURE/);fail=false;
 assert.equal(write({phase:'fatal'},{now:1003}),true);
 fs.unlinkSync(file);assert.equal(write({phase:'fatal'},{now:1004}),true);
 assert.equal(write({phase:'fatal'},{now:900}),true);
 assert.equal(JSON.parse(fs.readFileSync(file)).at,900);
});
