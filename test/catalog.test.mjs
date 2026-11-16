import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { makeRequest, normalizeResponse, installCatalogGuard, decodeResponse } from '../src/catalog-api.mjs';
import { CatalogWatcher, dateJST, safeTitle } from '../src/catalog-watch.mjs';
import { eventIssue, Issues } from '../src/error-monitor.mjs';
const config={target:'99',username:'test'};
const img=(id='11')=>({pk:id,media_type:1,taken_at:1792080000,image_versions2:{candidates:[{url:'https://s.cdninstagram.com/a.jpg',width:100,height:100}]}});
const video=(id='12')=>({pk:id,media_type:2,taken_at:1792080000,video_versions:[{url:'https://s.cdninstagram.com/a.mp4',width:100,height:100}]});
const post=(id='1')=>({pk:id,media_type:8,taken_at:1792080000,user:{pk:'99'},caption:{text:'caption 日本語'},carousel_media:[img(id+'1'),video(id+'2')],carousel_media_count:2,code:'ABC'});
const body=(posts=[post()],more=false,cursor=null)=>({data:{xdt_api__v1__feed__user_timeline_graphql_connection:{edges:posts.map(node=>({node})),page_info:{has_next_page:more,end_cursor:cursor}}}});
const wrap=r=>({version:1,target:'99',guard:{allowedQuery:1,blockedReadReceipt:0},...r});
function fixture(t,options={}){const root=fs.mkdtempSync(path.join(os.tmpdir(),'ig-catalog-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));const media=path.join(root,'media');fs.mkdirSync(media);const log=[];const args={root:media,stateDir:root,target:'99',username:'test',log:(event,data)=>log.push({event,...data}),...options};return {root,media,log,args,watch:new CatalogWatcher(args)};}
test('posts: carousel video preserved, caption and pagination strictness',()=>{
 const r=normalizeResponse(body(),{kind:'posts',cursor:null},'99');assert.deepEqual(r.posts[0].media.map(m=>m.mediaType),[1,2]);assert.equal(r.posts[0].caption,'caption 日本語');
 const bad=post();delete bad.carousel_media[1].video_versions;bad.carousel_media[1].image_versions2=img().image_versions2;
 assert.throws(()=>normalizeResponse(body([bad]),{kind:'posts',cursor:null},'99'),/VIDEO_VARIANT_MISSING/);
 assert.throws(()=>normalizeResponse(body([post()],true,null),{kind:'posts',cursor:null},'99'),/PAGINATION_INVALID/);
 assert.throws(()=>normalizeResponse(body(),{kind:'posts',cursor:null},'100'),/OWNER_MISMATCH/);
 assert.throws(()=>decodeResponse({status:200,text:'<html>error</html>'}),/NON_JSON/);
 assert.equal(decodeResponse({status:200,text:'for (;;);{"status":"ok"}'}).status,'ok');
});
test('highlight normalization requires requested ID and target owner',()=>{
 const plan={kind:'highlight',id:'77'};
 const r=normalizeResponse({data:{xdt_api__v1__feed__reels_media__connection:{edges:[{node:{id:'highlight:77',user:{pk:'99'},items:[img()]}}],page_info:{has_next_page:false,has_previous_page:false}}}},plan,'99');assert.equal(r.media.length,1);
 assert.throws(()=>normalizeResponse({data:{xdt_api__v1__feed__reels_media__connection:{edges:[{node:{id:'highlight:77',user:{pk:'100'},items:[]}}],page_info:{has_next_page:false,has_previous_page:false}}}},plan,'99'),/OWNER/);
 assert.throws(()=>normalizeResponse({reels:{}},plan,'99'),/SCHEMA/);
 assert.equal(dateJST(Date.parse('2026-10-15T16:30:00Z')/1000),'20261016_013000_JST');
 assert.equal(safeTitle('../a/b:*'), '_a_b__');
});
async function guard(spec){let handler;const stats=await installCatalogGuard({route:async(_,h)=>handler=h},spec);return {stats,request:async(url,method,body='',resource='fetch')=>{let action;await handler({request:()=>({url:()=>url,method:()=>method,postData:()=>body,resourceType:()=>resource,isNavigationRequest:()=>resource==='document'}),abort:async()=>action='blocked',continue:async()=>action='allowed'});return action;}};}
test('network guard permits only exact planned reads and blocks seen/write/wrong target/replay',async()=>{
 const spec=makeRequest({kind:'posts',cursor:null},config),g=await guard(spec);
 const form=new URLSearchParams({fb_api_req_friendly_name:spec.friendly,doc_id:spec.doc,variables:JSON.stringify(spec.variables)});
 assert.equal(await g.request('https://www.instagram.com/graphql/query','POST',form.toString()),'allowed');
 assert.equal(await g.request('https://www.instagram.com/graphql/query','POST',form.toString()),'blocked');
 const other=await guard(spec);form.set('variables',JSON.stringify({...spec.variables,username:'someone_else'}));assert.equal(await other.request('https://www.instagram.com/graphql/query','POST',form.toString()),'blocked');
 assert.equal(await other.request('https://www.instagram.com/api/v1/media/seen/','POST',''),'blocked');assert.equal(other.stats.blockedReadReceipt,1);
 assert.equal(await other.request('https://www.instagram.com/api/v1/likes/','POST',''),'blocked');
 const reel=makeRequest({kind:'highlight',id:'77'},config),rg=await guard(reel);
 assert.equal(await rg.request('https://www.instagram.com'+reel.path,'POST',new URLSearchParams({user_ids:'["highlight:78"]'}).toString()),'blocked');
 assert.equal(await rg.request('https://www.instagram.com'+reel.path,'POST',new URLSearchParams({fb_api_req_friendly_name:reel.friendly,doc_id:reel.doc,variables:JSON.stringify(reel.variables)}).toString()),'allowed');
});
test('stable indexing, caption edits, baseline quiet, new media notify, independent retries and restart',async t=>{
 let fail=true,sends=0,downloads=0;
 const f=fixture(t,{downloader:async(root,base,a)=>{downloads++;if(fail)throw Object.assign(Error(),{code:'ENOSPC'});return {relativePath:base+(a.mediaType===2?'.mp4':'.jpg'),bytes:100};}});
 let w=f.watch;const plan={kind:'posts',cursor:null};w.ingest(plan,wrap(normalizeResponse(body(),plan,'99')));w.persist();
 assert.equal(Object.values(w.state.assets).every(a=>a.telegramDone),true);
 assert.match(w.state.posts.records['1'].folder,/^posts\/00001_\d{8}_\d{6}_JST$/);
 await w.deliver(new AbortController().signal,async()=>{sends++;});assert.equal(sends,0);assert.equal(Object.values(w.state.assets).every(a=>!a.archiveDone),true);
 w=new CatalogWatcher(f.args);fail=false;
 const attempts=downloads;await w.deliver(new AbortController().signal,async()=>{sends++;});assert.equal(downloads,attempts,'failed assets retain retry delay across restart');
 const retryTime=Date.now()+60001;t.mock.method(Date,'now',()=>retryTime);
 await w.deliver(new AbortController().signal,async()=>{sends++;});assert.equal(Object.values(w.state.assets).every(a=>a.archiveDone),true);
 const oldFolder=w.state.posts.records['1'].folder;const changed=post();changed.caption.text='edited';
 w.ingest(plan,wrap(normalizeResponse(body([post('2'),changed]),plan,'99')));w.persist();assert.equal(w.state.posts.records['1'].folder,oldFolder);
 await w.deliver(new AbortController().signal,async()=>{throw Error('TELEGRAM_ERROR_500');});assert.equal(w.state.assets['post:2:21'].archiveDone,true);assert.equal(w.state.assets['post:2:21'].telegramDone,false);
 const before=downloads;w=new CatalogWatcher(f.args);await w.deliver(new AbortController().signal,async()=>{sends++;});assert.equal(downloads,before);assert.equal(sends,1);
 assert.equal(fs.readFileSync(path.join(f.media,oldFolder,'caption.txt'),'utf8'),'edited');
});
test('highlight stable folder/title and per-highlight failure allows others to progress',async t=>{
 const f=fixture(t,{fetcher:async plan=>{if(plan.id==='77')throw Error('CATALOG_HTTP_403');return wrap({kind:'highlight',id:plan.id,media:[]});}});
 const w=f.watch;w.state.posts.nextAt=Date.now()+1e9;
 w.ingest({kind:'tray'},wrap({kind:'tray',highlights:[{id:'77',title:'a/b'},{id:'78',title:'旅行'}]}));
 await w.check(new AbortController().signal);assert.ok(w.state.highlights.todo[0].retryAt);
 await w.check(new AbortController().signal);assert.ok(w.state.highlights.records['78']);assert.equal(w.state.highlights.baseline,false);
 assert.equal(f.log.find(x=>x.event==='CATALOG_CHECK_FAILED').scope,'highlight:77');
});
test('schema failure preserves pagination checkpoint and emits issue; corrupt state fails closed',async t=>{
 const f=fixture(t,{fetcher:async()=>wrap({kind:'posts',posts:[{id:'oops'}],hasNext:false})});
 f.watch.state.highlights.nextAt=Date.now()+1e9;
 await f.watch.check(new AbortController().signal);
 assert.equal(f.watch.state.posts.cursor,null);assert.equal(Object.keys(f.watch.state.posts.records).length,0);
 const row=f.log.find(x=>x.event==='CATALOG_CHECK_FAILED');assert.deepEqual(eventIssue(row),['catalog-fetch:posts','CATALOG_INVALID_POST']);
 fs.writeFileSync(f.watch.file,'{');assert.throws(()=>new CatalogWatcher(f.args),/HISTORY_READ/);
});
test('multi-page baseline remains quiet and repeated cursor cannot mark complete',async t=>{
 const f=fixture(t),w=f.watch;
 let plan={kind:'posts',cursor:null};w.ingest(plan,wrap(normalizeResponse(body([post('1')],true,'page2'),plan,'99')));
 assert.equal(w.state.posts.baseline,false);assert.equal(w.state.posts.cursor,'page2');
 plan={kind:'posts',cursor:'page2'};w.ingest(plan,wrap(normalizeResponse(body([post('2')],false),plan,'99')));
 assert.equal(w.state.posts.baseline,true);assert.ok(Object.values(w.state.assets).every(a=>a.telegramDone));
 assert.equal(w.state.posts.records['2'].index,2);
});

test('failed captions rotate so later captions can still be saved', async t => {
 const f=fixture(t),w=f.watch;
 // A regular file in place of a directory makes the first ten writes fail.
 fs.writeFileSync(path.join(f.media,'posts'),'blocked');
 for(let i=0;i<10;i++) w.state.captions[String(i)]={file:`posts/${i}/caption.txt`,text:'blocked',hash:'blocked'};
 w.state.captions['10']={file:'highlight/later/caption.txt',text:'later',hash:'later'};
 await w.deliver(new AbortController().signal,async()=>{});
 assert.equal(w.state.captions['10'].savedHash,undefined);
 const restarted=new CatalogWatcher(f.args);
 await restarted.deliver(new AbortController().signal,async()=>{});
 assert.equal(fs.readFileSync(path.join(f.media,'highlight/later/caption.txt'),'utf8'),'later');
 assert.equal(restarted.state.captions['10'].savedHash,'later');
});

test('profile pagination accepts confirmed coauthors but rejects invitations and unrelated owners', () => {
 const collaboration=post();collaboration.user={pk:'77247833372'};collaboration.coauthor_producers=[{id:'99'}];
 const plan={kind:'posts',cursor:'page-two'};
 assert.equal(normalizeResponse(body([collaboration]),plan,'99').posts.length,1);
 collaboration.coauthor_producers=[{pk:'99'}];
 assert.equal(normalizeResponse(body([collaboration]),plan,'99').posts.length,1);
 collaboration.coauthor_producers=[{id:'123'}];collaboration.invited_coauthor_producers=[{id:'99'}];
 assert.throws(()=>normalizeResponse(body([collaboration]),plan,'99'),/OWNER_MISMATCH/);
 delete collaboration.user;collaboration.coauthor_producers=[{id:'99'}];
 assert.throws(()=>normalizeResponse(body([collaboration]),plan,'99'),/OWNER_MISMATCH/);
 const tray={data:{highlights:{edges:[{node:{id:'highlight:77',title:'x',user:{pk:'123'},coauthor_producers:[{id:'99'}]}}],page_info:{has_next_page:false,has_previous_page:false}}}};
 assert.throws(()=>normalizeResponse(tray,{kind:'tray'},'99'),/OWNER_MISMATCH/);
});

test('post catalog can ignore only the known unused location image field exception', () => {
 const response = body();
 const locationError = {message:'A server error field_exception occured. Check server logs for details.',severity:'ERROR',path:['xdt_api__v1__feed__user_timeline_graphql_connection','edges',0,'node','location','profile_pic_url']};
 response.errors = [locationError];
 const raw = value => ({status:200,text:JSON.stringify(value)});
 const options = {allowPostLocationImageError:true};
 assert.throws(()=>decodeResponse(raw(response)),/SERVER_OR_GRAPHQL_ERROR/,'manual and default callers stay strict');
 const decoded = decodeResponse(raw(response), options);
 assert.equal(normalizeResponse(decoded,{kind:'posts',cursor:null},'99').posts.length,1);
 for (const error of [
   {...locationError,path:['xdt_viewer','profile_pic_url']},
   {...locationError,path:['xdt_api__v1__feed__user_timeline_graphql_connection','edges',0,'node','user','profile_pic_url']},
   {...locationError,path:['xdt_api__v1__feed__user_timeline_graphql_connection','edges',0,'node','video_versions']},
   {...locationError,path:['xdt_api__v1__feed__user_timeline_graphql_connection','edges',9,'node','location','profile_pic_url']},
   {...locationError,message:'Permission denied'},
 ]) assert.throws(()=>decodeResponse(raw({...response,errors:[error]}),options),/SERVER_OR_GRAPHQL_ERROR/);
 assert.throws(()=>decodeResponse(raw({...response,errors:[locationError,{message:'Rate limited'}]}),options),/SERVER_OR_GRAPHQL_ERROR/);
 assert.throws(()=>decodeResponse(raw({...response,status:'fail'}),options),/SERVER_OR_GRAPHQL_ERROR/);
 assert.throws(()=>decodeResponse(raw({...response,error:123}),options),/SERVER_OR_GRAPHQL_ERROR/);
 const invalid = structuredClone(response); delete invalid.data.xdt_api__v1__feed__user_timeline_graphql_connection.edges[0].node.carousel_media[0].image_versions2;
 assert.throws(()=>normalizeResponse(decodeResponse(raw(invalid),options),{kind:'posts',cursor:null},'99'),/IMAGE_VARIANT_MISSING/);
});

test('latest posts preempt history and preserve checkpoint across restart without duplicate delivery', async t => {
 const calls=[];
 const f=fixture(t,{fetcher:async plan=>{
  calls.push(plan.cursor);
  return wrap(normalizeResponse(body([post(plan.cursor?'3':'2')],true,plan.cursor?'page3':'page2'),plan,'99'));
 },downloader:async(root,base,a)=>({relativePath:base+'.jpg',bytes:100})});
 let w=f.watch;
 w.state.posts.baseline=true;w.state.posts.cursor='page2';w.state.posts.cursors=['page2'];
 w.state.highlights.nextAt=Date.now()+1e9;
 await w.check(new AbortController().signal);
 assert.deepEqual(calls,[null,'page2']);
 assert.equal(w.state.posts.cursor,'page3');
 assert.deepEqual(w.state.posts.cursors,['page2','page3']);
 assert.equal(w.state.assets['post:2:21'].telegramDone,false);
 let sends=0;await w.deliver(new AbortController().signal,async()=>{sends++;});
 assert.equal(sends,2);
 w=new CatalogWatcher(f.args);w.state.posts.latestScan.nextAt=0;w.state.posts.nextAt=Date.now()+1e9;
 calls.length=0;
 await w.check(new AbortController().signal);
 assert.deepEqual(calls,[null]);
 assert.equal(w.state.posts.cursor,'page3');
 await w.deliver(new AbortController().signal,async()=>{sends++;});assert.equal(sends,2);
});

test('latest page failure backs off independently while history progresses', async t => {
 const calls=[];const f=fixture(t,{fetcher:async plan=>{
  calls.push(plan.cursor);if(!plan.cursor)throw Error('CATALOG_HTTP_429');
  return wrap(normalizeResponse(body([post('3')],true,'page3'),plan,'99'));
 }});const w=f.watch;
 w.state.posts.baseline=true;w.state.posts.cursor='page2';w.state.posts.cursors=['page2'];w.state.highlights.nextAt=Date.now()+1e9;
 await w.check(new AbortController().signal);
 assert.deepEqual(calls,[null,'page2']);assert.equal(w.state.posts.cursor,'page3');
 assert.equal(w.state.posts.latestScan.failures,1);assert.ok(w.state.posts.latestScan.nextAt>Date.now());
 w.state.assets={};w.state.captions={};assert.equal(await w.deliver(new AbortController().signal,async()=>{}),false);
});

test('regular first page clears latest-page failure after history completes', async t => {
 let fail=true;
 const f=fixture(t,{fetcher:async plan=>{
  if(!plan.cursor&&fail)throw Error('CATALOG_HTTP_429');
  return wrap(normalizeResponse(body([]),plan,'99'));
 }});const w=f.watch;
 w.state.posts.baseline=true;w.state.posts.cursor='last';w.state.posts.cursors=['last'];w.state.highlights.nextAt=Date.now()+1e9;
 await w.check(new AbortController().signal);
 assert.equal(w.state.posts.cursor,null);assert.equal(w.state.posts.latestScan.failures,1);
 fail=false;w.state.posts.nextAt=0;
 await w.check(new AbortController().signal);
 assert.equal(w.state.posts.latestScan.failures,0);
 assert.ok(f.log.some(row=>row.event==='CATALOG_CHECK_OK'&&row.scope==='posts:latest'));
});

test('new carousel sends one ordered mixed album with caption once and retries as a unit', async t => {
 const f=fixture(t,{downloader:async(root,base,a)=>({relativePath:base+'.jpg',bytes:100})});const w=f.watch;
 w.state.posts.baseline=true;const plan={kind:'posts',cursor:null};
 w.ingest(plan,wrap(normalizeResponse(body([post('7')]),plan,'99')));w.persist();
 const failed=[];
 await w.deliver(new AbortController().signal,async(method,body)=>{failed.push({method,body});throw Error('TELEGRAM_ERROR_500');});
 assert.equal(failed.length,1);assert.equal(failed[0].method,'sendMediaGroup');
 assert.deepEqual(failed[0].body.media.map(m=>m.type),['photo','video']);
 assert.match(failed[0].body.media[0].caption,/caption 日本語/);assert.equal(failed[0].body.media[1].caption,undefined);
 assert.ok(Object.values(w.state.assets).every(a=>!a.telegramDone));
 const restarted=new CatalogWatcher(f.args),sent=[];
 await restarted.deliver(new AbortController().signal,async(method,body,metadata)=>{sent.push({method,body,metadata});});
 assert.equal(sent.length,1);assert.equal(sent[0].metadata.ids.length,2);
 assert.ok(Object.values(restarted.state.assets).every(a=>a.telegramDone));
 await restarted.deliver(new AbortController().signal,async()=>assert.fail('duplicate album'));
});

test('large post splits at ten without repeating caption or mixing posts and keeps partial acknowledgements',async t=>{
 const f=fixture(t,{downloader:async(root,base,a)=>({relativePath:base+'.jpg',bytes:100})}),w=f.watch;
 w.state.posts.baseline=true;const plan={kind:'posts',cursor:null};
 const large={...post('8'),carousel_media:Array.from({length:12},(_,i)=>img(String(800+i))),carousel_media_count:12};
 w.ingest(plan,wrap(normalizeResponse(body([large,post('9')]),plan,'99')));w.persist();
 const calls=[];await w.deliver(new AbortController().signal,async(method,body)=>{calls.push({method,body});if(calls.length===2)throw Error('TELEGRAM_ERROR_429');});
 assert.deepEqual(calls.map(c=>c.body.media.length),[10,2]);assert.ok(calls[0].body.media[0].caption);assert.ok(calls[1].body.media.every(m=>m.caption===undefined));
 const restarted=new CatalogWatcher(f.args),retry=[];
 await restarted.deliver(new AbortController().signal,async(method,body,metadata)=>retry.push({method,body,metadata}));
 assert.deepEqual(retry.map(c=>c.body.media.length),[2,2]);
 assert.ok(retry.find(c=>c.metadata.ids[0].startsWith('post:8:')).body.media.every(m=>m.caption===undefined));assert.ok(retry.find(c=>c.metadata.ids[0].startsWith('post:9:')).body.media[0].caption);
 assert.ok(Object.values(restarted.state.assets).every(a=>a.telegramDone));
});

test('catalog dispatches more work before checkpoint timer, then durably flushes every completion', async t => {
 let downloads=0;
 const f=fixture(t,{downloader:async(root,base)=>{downloads++;return {relativePath:base+'.jpg',bytes:100};}});
 const w=f.watch,plan={kind:'posts',cursor:null};
 w.ingest(plan,wrap(normalizeResponse(body(Array.from({length:6},(_,i)=>post(String(i+1)))),plan,'99')));
 w.state.captions={};w.persist();
 const run=w.deliver(new AbortController().signal,async()=>{});
 try {
  await new Promise(resolve=>setTimeout(resolve,400));
  assert.equal(downloads,12,'downloads must not wait one second per worker after each file');
 } finally { await run; }
 const restarted=new CatalogWatcher(f.args);
 assert.equal(Object.values(restarted.state.assets).filter(a=>a.archiveDone).length,12);
});

test('caption and media failures respect retry deadlines during background draining', async t => {
 let downloads=0;const f=fixture(t,{downloader:async()=>{downloads++;throw Error('NETWORK');}});
 fs.writeFileSync(path.join(f.media,'posts'),'blocked');
 f.watch.state.captions.one={file:'posts/one/caption.txt',hash:'new',text:'caption'};
 f.watch.state.assets.one={key:'one',base:'posts/one/01',id:'11',mediaType:1,mediaUrl:'https://s.cdninstagram.com/a.jpg',archiveDone:false,telegramDone:true};
 await f.watch.deliver(new AbortController().signal,async()=>{});
 const before=f.log.filter(row=>row.event==='CATALOG_CAPTION_RETRY').length;
 const restarted=new CatalogWatcher(f.args);
 await restarted.deliver(new AbortController().signal,async()=>{});
 assert.equal(downloads,1);
 assert.equal(f.log.filter(row=>row.event==='CATALOG_CAPTION_RETRY').length,before);
 const due=Date.now()+60001;t.mock.method(Date,'now',()=>due);
 await restarted.deliver(new AbortController().signal,async()=>{});
 assert.equal(downloads,2);
 assert.equal(f.log.filter(row=>row.event==='CATALOG_CAPTION_RETRY').length,before+1);
});
