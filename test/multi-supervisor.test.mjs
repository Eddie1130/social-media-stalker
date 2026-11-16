import { createHealthWriter } from '../src/health-writer.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import vm from 'node:vm';
import readline from 'node:readline';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { Issues, atomic, load, safe, eventIssue } from '../src/error-monitor.mjs';
import { targetIssueKey } from '../src/targets.mjs';

test('real supervisor clears persistent session/runtime/legacy issues after worker restart and scopes recovery', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ig-supervisor-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const monitor = path.join(dir, 'monitor'), file = path.join(monitor, 'issues.json');
  const issues = new Issues(file, path.join(monitor, 'outbox'), '@alice');
  issues.fail('shared-session', 'SESSION_INVALID_RELOGIN_REQUIRED');
  issues.fail('target:alice:target-runtime', 'INVALID_MEDIA_STATE');
  issues.fail('target:bob:target-runtime', 'INVALID_MEDIA_STATE');
  issues.fail('fetch', 'FETCH_TIMEOUT');
  fs.writeFileSync(path.join(dir, 'watch-media-101.json'), '{}');
  const processMock = new EventEmitter();
  processMock.env = { IG_MONITOR_DIR: monitor, IG_TARGET_USERNAMES: 'alice,bob' };
  processMock.kill = () => {}; processMock.exit = () => assert.fail('supervisor must not exit fatally');
  const source = fs.readFileSync(new URL('../src/watch-supervisor.mjs', import.meta.url), 'utf8').replace(/^import .*;\n/gm, '');
  const spawn = () => {
    const worker = new EventEmitter(); worker.pid = 123;
    worker.stdout = new PassThrough(); worker.stderr = new PassThrough();
    setImmediate(() => {
      // The fresh worker has no knowledge of the prior invalid session/runtime error.
      for (const row of [
        { event: 'WATCH_TARGET_READY', target: '101', username: 'alice' },
        { event: 'WATCH_MEDIA_CHECK_OK', target: '101', username: 'alice', skippedCount: 0, skippedIds: [], mediaIds: [], storyCount: 0 },
        { event: 'WATCH_TARGET_COMPLETED', target: '101', username: 'alice' },
      ]) worker.stdout.write(JSON.stringify(row) + '\n');
      worker.stdout.end(); worker.stderr.end();
      processMock.emit('SIGTERM'); worker.emit('close', 0, null);
    });
    return worker;
  };
  const sandbox = vm.createContext({ fs, path, readline, spawn, Issues, atomic, load, safe, eventIssue, targetIssueKey, createHealthWriter,
    log: () => {}, console: { log: () => {} }, process: processMock, setInterval, clearInterval, setTimeout });
  await vm.runInContext(source, sandbox);
  const state = load(file);
  assert.equal(state['shared-session'].active, false);
  assert.equal(state['target:alice:target-runtime'].active, false);
  assert.equal(state['target:bob:target-runtime'].active, true, 'Alice recovery cannot clear Bob runtime issue');
  assert.equal(state['target:alice:fetch'].active, false);
  assert.equal(Object.hasOwn(state, 'fetch'), false);
});

for(const attempts of [2,3])test(`real supervisor gates catalog errors after ${attempts} failed polls and resets on success`,async t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'ig-supervisor-retry-'));
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const monitor=path.join(dir,'monitor'),file=path.join(monitor,'issues.json'),outbox=path.join(monitor,'outbox');
  const processMock=new EventEmitter();processMock.env={IG_MONITOR_DIR:monitor};processMock.kill=()=>{};
  processMock.exit=()=>assert.fail('must not exit fatally');
  const source=fs.readFileSync(new URL('../src/watch-supervisor.mjs',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
  const spawn=()=>{
    const worker=new EventEmitter();worker.pid=123;worker.stdout=new PassThrough();worker.stderr=new PassThrough();
    setImmediate(()=>{
      for(let i=0;i<attempts;i++)worker.stdout.write(JSON.stringify({event:'CATALOG_CHECK_FAILED',target:'101',username:'alice',scope:'posts',reason:`CATALOG_HTTP_${500+i}`})+'\n');
      assert.equal(load(file)['target:alice:catalog-fetch:posts'].active,attempts===3);
      worker.stdout.write(JSON.stringify({event:'CATALOG_CHECK_OK',target:'101',username:'alice',scope:'posts'})+'\n');
      worker.stdout.end();worker.stderr.end();processMock.emit('SIGTERM');worker.emit('close',0,null);
    });return worker;
  };
  const sandbox=vm.createContext({fs,path,readline,spawn,Issues,atomic,load,safe,eventIssue,targetIssueKey,createHealthWriter,
    log:()=>{},console:{log:()=>{}},process:processMock,setInterval,clearInterval,setTimeout});
  await vm.runInContext(source,sandbox);
  assert.equal(load(file)['target:alice:catalog-fetch:posts'].count,0);
  assert.equal(fs.existsSync(outbox)?fs.readdirSync(outbox).length:0,attempts===3?2:0);
});

test('supervisor coalesces progress bursts but publishes errors and shutdown immediately',async t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'ig-supervisor-health-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const monitor=path.join(dir,'monitor'),file=path.join(monitor,'health.json');let writes=0;
  const countedAtomic=(p,value)=>{if(p===file)writes++;atomic(p,value);};
  const healthFactory=(p,options)=>createHealthWriter(p,{...options,writer:countedAtomic});
  const processMock=new EventEmitter();processMock.env={IG_MONITOR_DIR:monitor};processMock.kill=()=>{};processMock.exit=()=>assert.fail('must not exit fatally');
  const source=fs.readFileSync(new URL('../src/watch-supervisor.mjs',import.meta.url),'utf8').replace(/^import .*;\n/gm,'');
  const spawn=()=>{
    const worker=new EventEmitter();worker.pid=123;worker.stdout=new PassThrough();worker.stderr=new PassThrough();
    setImmediate(()=>{
      for(let i=0;i<30;i++)worker.stdout.write(JSON.stringify({event:'CATALOG_MEDIA_SAVED',target:'101',username:'alice',key:String(i)})+'\n');
      assert.ok(writes<=2,'ordinary progress must not write on every event');
      const before=writes;
      worker.stdout.write(JSON.stringify({event:'CATALOG_CHECK_FAILED',target:'101',username:'alice',scope:'posts',reason:'CATALOG_HTTP_500'})+'\n');
      assert.equal(writes,before+1);assert.equal(load(file).lastEvent,'CATALOG_CHECK_FAILED');
      worker.stdout.end();worker.stderr.end();processMock.emit('SIGTERM');worker.emit('close',0,null);
    });return worker;
  };
  await vm.runInContext(source,vm.createContext({fs,path,readline,spawn,Issues,atomic:countedAtomic,load,safe,eventIssue,targetIssueKey,createHealthWriter:healthFactory,
    log:()=>{},console:{log:()=>{}},process:processMock,setInterval,clearInterval,setTimeout}));
  assert.equal(load(file).phase,'stopped');assert.ok(writes<=4);
});
