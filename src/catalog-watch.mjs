import { archiveLimits } from './archive-pressure.mjs';
import { AtomicStateStore } from './atomic-state-store.mjs';
import { ArchiveProgress } from './archive-progress.mjs';
import { record } from './performance-metrics.mjs';
import { archiveBatch } from './archive-batch.mjs';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import readline from 'node:readline';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { atomic } from './error-monitor.mjs';
import { downloadStory, archiveReason } from './story-archive.mjs';
import { validMediaUrl } from './story-media.mjs';
import { sessionInvalid } from './targets.mjs';
import { idOK, highlightId } from './catalog-api.mjs';

export function dateJST(seconds) {
  const d=new Date(Number(seconds)*1000+9*3600000);
  if(!Number.isFinite(d.getTime())||Number(seconds)<=0) throw Error('CATALOG_INVALID_TIME');
  return d.toISOString().slice(0,19).replaceAll('-','').replace('T','_').replaceAll(':','')+'_JST';
}
export function safeTitle(text) {
  return [...String(text||'highlight').replace(/[\\/:*?"<>|\x00-\x1f\x7f]/g,'_').replace(/\s+/g,' ').trim().replace(/^[. ]+|[. ]+$/g,'')].slice(0,50).join('')||'highlight';
}
const hash=text=>createHash('sha256').update(text).digest('hex');
const obj=v=>v && typeof v==='object' && !Array.isArray(v);
const safeReason=e=>/^CATALOG_[A-Z0-9_]+$/.test(e?.message||'')?e.message:archiveReason(e);
const sequence=n=>String(n).padStart(5,'0');
export async function fetchCatalog(plan,{signal,onChild=()=>{},script='/app/src/fetch-catalog.mjs',env=process.env}={}) {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'ig-catalog-')),result=path.join(dir,'result.json');
  try {
    await new Promise((resolve,reject)=>{
      const child=spawn(process.execPath,[script],{detached:true,stdio:['ignore','pipe','pipe'],env:{...env,IG_CATALOG_PLAN:JSON.stringify(plan),IG_CATALOG_RESULT_FILE:result}});
      onChild(child);let success=false,reason='CATALOG_FETCH_FAILED';
      const kill=()=>{try{process.kill(-child.pid,'SIGKILL');}catch{}};
      const timer=setTimeout(()=>{reason='CATALOG_FETCH_TIMEOUT';kill();},115000);
      signal?.addEventListener('abort',kill,{once:true});if(signal?.aborted)kill();
      readline.createInterface({input:child.stdout}).on('line',line=>{try{const r=JSON.parse(line);if(r.event==='CATALOG_HTTP_DIAGNOSTIC'&&['tray','highlight'].includes(r.kind)&&Number.isInteger(r.status)&&['www.instagram.com','i.instagram.com'].includes(r.host))console.log(JSON.stringify({ts:new Date().toISOString(),event:r.event,target:env.IG_TARGET_USER_ID,username:env.IG_TARGET_USERNAME,kind:r.kind,transport:'context_request',status:r.status,host:r.host,redirects:r.redirects}));if(r.event==='CATALOG_OWNER_DIAGNOSTIC')console.log(JSON.stringify({ts:new Date().toISOString(),event:r.event,target:env.IG_TARGET_USER_ID,username:env.IG_TARGET_USERNAME,paginated:r.paginated,owners:r.owners}));if(r.event==='CATALOG_FETCH_SUCCESS')success=true;if(r.event==='CATALOG_FETCH_ERROR'&&/^CATALOG_[A-Z0-9_]+$/.test(r.reason))reason=r.reason;}catch{}});
      child.stderr.resume();
      child.on('error',()=>{reason='CATALOG_PROCESS_START_ERROR';});
      child.on('close',code=>{clearTimeout(timer);signal?.removeEventListener('abort',kill);onChild(null);if(code===0&&success&&!signal?.aborted)resolve();else reject(Error(reason));});
    });
    return JSON.parse(fs.readFileSync(result,'utf8'));
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
}
export class CatalogWatcher {
  constructor({root,stateDir,target,username,log,fetcher=fetchCatalog,downloader=downloadStory,postsInterval=900,highlightsInterval=900}) {
    if(!path.isAbsolute(root)||!/^\d+$/.test(target))throw Error('CATALOG_INVALID_CONFIG');
    for(const n of [postsInterval,highlightsInterval])if(!Number.isInteger(n)||n<300||n>86400)throw Error('CATALOG_INVALID_INTERVAL');
    Object.assign(this,{root,target,username,log,fetcher,downloader,postsInterval,highlightsInterval});
    this.file=path.join(stateDir,`catalog-${target}.json`);this.required=this.file+'.required';
    if(fs.existsSync(this.required)&&!fs.existsSync(this.file))throw Error('CATALOG_HISTORY_MISSING');
    try{this.state=JSON.parse(fs.readFileSync(this.file,'utf8'));}
    catch(e){if(e.code!=='ENOENT')throw Error('CATALOG_HISTORY_READ_OR_PARSE_ERROR');this.state={version:1,target,
      posts:{baseline:false,cursor:null,cursors:[],nextAt:0,failures:0,nextIndex:1,records:{}},
      highlights:{baseline:false,todo:[],nextAt:0,failures:0,nextIndex:1,records:{}},assets:{},captions:{}};}
    const s=this.state;
    if(s.version!==1||s.target!==target||!obj(s.posts)||!obj(s.highlights)||!obj(s.assets)||!obj(s.captions))throw Error('CATALOG_INVALID_HISTORY');
    for(const group of [s.posts,s.highlights])if(!obj(group.records)||typeof group.baseline!=='boolean'||!Number.isInteger(group.nextIndex)||group.nextIndex<1||!Number.isFinite(group.nextAt)||!Number.isInteger(group.failures)||group.failures<0)throw Error('CATALOG_INVALID_HISTORY');
    if(!Array.isArray(s.highlights.todo)||!Array.isArray(s.posts.cursors)||(s.posts.cursor!==null&&typeof s.posts.cursor!=='string'))throw Error('CATALOG_INVALID_HISTORY');
    s.posts.latestScan ??= {nextAt:0,failures:0};
    if(!obj(s.posts.latestScan)||!Number.isFinite(s.posts.latestScan.nextAt)||!Number.isInteger(s.posts.latestScan.failures)||s.posts.latestScan.failures<0)throw Error('CATALOG_INVALID_HISTORY');
    for(const record of Object.values(s.posts.records))this.full(record.folder);
    for(const record of Object.values(s.highlights.records))this.full(record.folder);
    for(const asset of Object.values(s.assets)) {
      this.full(asset.base);
      if(!validMediaUrl(asset.mediaUrl)||!idOK(asset.id)||![1,2].includes(asset.mediaType)||typeof asset.archiveDone!=='boolean'||typeof asset.telegramDone!=='boolean')throw Error('CATALOG_INVALID_ASSET_HISTORY');
    }
    for(const caption of Object.values(s.captions)){this.full(caption.file);if(typeof caption.text!=='string')throw Error('CATALOG_INVALID_CAPTION_HISTORY');}
    this.persist();
  }
  full(relative) {
    if(typeof relative!=='string'||! /^(posts|highlight)\//.test(relative)||relative.split(/[\\/]/).some(x=>!x||x==='.'||x==='..')||path.isAbsolute(relative))throw Error('CATALOG_INVALID_PATH');
    const file=path.resolve(this.root,relative);
    if(!file.startsWith(path.resolve(this.root)+path.sep))throw Error('CATALOG_INVALID_PATH');return file;
  }
  persist(){atomic(this.file,this.state);this.asyncStore=null;if(!fs.existsSync(this.required))fs.writeFileSync(this.required,'required',{flag:'wx',mode:0o600});}
  async persistAsync(){
    this.asyncStore ||= new AtomicStateStore({file:this.file,initial:this.state});
    const snapshot=structuredClone(this.state),started=performance.now();
    await this.asyncStore.transact(()=>snapshot);
    record('settings_commit',performance.now()-started,{platform:'ig',outcome:'ok'});
  }
  addAsset(kind,parent,part,record,title,code,quiet) {
    if(!idOK(part.id)||!validMediaUrl(part.mediaUrl)||![1,2].includes(part.mediaType))throw Error('CATALOG_INVALID_MEDIA');
    const key=`${kind}:${parent}:${part.id}`,old=this.state.assets[key];
    const index=record.parts[part.id] ?? (record.parts[part.id]=record.nextPart++);
    const base=kind==='post'?`${record.folder}/${String(index).padStart(2,'0')}`:`${record.folder}/${String(index).padStart(3,'0')}_${dateJST(part.takenAt)}`;
    this.full(base);
    this.state.assets[key]={...old,...part,key,kind,parent,title,code,base:old?.base||base,archiveDone:old?.archiveDone??false,telegramDone:old?.telegramDone??quiet,detectedAt:old?.detectedAt??Date.now(),lastAttemptAt:old?.lastAttemptAt??0};
  }
  ingest(plan,result) {
    if(result.version!==1||result.target!==this.target||result.kind!==plan.kind||result.guard?.blockedReadReceipt!==0||result.guard?.allowedQuery!==1)throw Error('CATALOG_UNTRUSTED_RESULT');
    const {posts,highlights}=this.state;
    if(plan.kind==='posts') {
      if(!Array.isArray(result.posts)||typeof result.hasNext!=='boolean')throw Error('CATALOG_INVALID_POSTS_RESULT');
      if(result.hasNext && (typeof result.cursor!=='string'||!result.cursor||(!plan.latest&&posts.cursors.includes(result.cursor))))throw Error('CATALOG_PAGINATION_LOOP');
      for(const post of result.posts) {
        if(!idOK(post.id)||!Array.isArray(post.media)||!post.media.length||typeof post.caption!=='string')throw Error('CATALOG_INVALID_POST');
        let record=posts.records[post.id];
        if(!record){const index=posts.nextIndex++;record=posts.records[post.id]={index,folder:`posts/${sequence(index)}_${dateJST(post.takenAt)}`,parts:{},nextPart:1};}
        this.state.captions[post.id]={...this.state.captions[post.id],file:record.folder+'/caption.txt',text:post.caption,hash:hash(post.caption)};
        for(const part of post.media)this.addAsset('post',post.id,part,record,'',post.code,!posts.baseline);
      }
      if(plan.cursor===null)posts.latestScan={nextAt:Date.now()+this.postsInterval*1000,failures:0};
      // Latest-page refreshes ingest media without changing the history checkpoint.
      if(plan.latest)return;
      posts.cursor=result.hasNext?result.cursor:null;
      if(result.hasNext){posts.cursors.push(result.cursor);posts.nextAt=0;}
      else{posts.cursors=[];posts.nextAt=Date.now()+this.postsInterval*1000;posts.baseline=true;}
      posts.failures=0;
    }else if(plan.kind==='tray'){
      if(!Array.isArray(result.highlights))throw Error('CATALOG_INVALID_TRAY_RESULT');
      highlights.lastTrayAt=Date.now();
      highlights.todo=result.highlights.map(h=>({id:highlightId(h.id),title:String(h.title)}));
      if(!highlights.todo.length){highlights.baseline=true;highlights.nextAt=Date.now()+this.highlightsInterval*1000;}
      else highlights.nextAt=0;
      highlights.failures=0;
    }else{
      if(result.id!==plan.id||!Array.isArray(result.media))throw Error('CATALOG_INVALID_REEL_RESULT');
      let record=highlights.records[plan.id];
      if(!record){const index=highlights.nextIndex++;record=highlights.records[plan.id]={index,folder:`highlight/${String(index).padStart(2,'0')}_${safeTitle(plan.title)}`,parts:{},nextPart:1};}
      for(const part of result.media)this.addAsset('highlight',plan.id,part,record,plan.title,null,!highlights.baseline);
      highlights.todo=highlights.todo.filter(h=>h.id!==plan.id);highlights.failures=0;
      if(!highlights.todo.length){highlights.baseline=true;highlights.nextAt=Date.now()+this.highlightsInterval*1000;}
      else highlights.nextAt=0;
    }
  }
  async check(signal,onChild,{shouldYield=()=>false}={}) {
    for(const task of ['latestPosts','posts','highlights']) {
      if(shouldYield())break;
      const latest=task==='latestPosts',group=latest?'posts':task;
      if(latest&&(!this.state.posts.baseline||!this.state.posts.cursor))continue;
      const state=latest?this.state.posts.latestScan:this.state[group];if(signal.aborted||Date.now()<state.nextAt)continue;
      const historical=!latest&&((group==='posts'&&!!state.cursor)||(group==='highlights'&&!state.baseline));
      if(historical&&!archiveLimits().allowHistoricalDiscovery){if(Date.now()-(this.lastHistoricalQuery||0)<60000)continue;this.lastHistoricalQuery=Date.now();}
      const refreshFailedTray = group === 'highlights' && state.todo.length > 0 && state.todo.every(h => h.failures > 0) && Date.now() - (state.lastTrayAt || 0) >= this.highlightsInterval * 1000;
      const due = group === 'highlights' ? state.todo.find(h => !h.retryAt || Date.now() >= h.retryAt) : null;
      if (group === 'highlights' && state.todo.length && !due && !refreshFailedTray) continue;
      const plan=group==='posts'?{kind:'posts',cursor:latest?null:state.cursor,...(latest?{latest:true}:{})}:refreshFailedTray?{kind:'tray'}:due?{kind:'highlight',...due}:{kind:'tray'};
      const scope=latest?'posts:latest':plan.kind==='highlight'?'highlight:'+plan.id:group;
      this.log('CATALOG_CHECK_STARTED',{group,scope,kind:plan.kind});
      // Restore the previous in-memory snapshot if validation fails midway.
      const snapshot=JSON.stringify(this.state);
      try {const result=await this.fetcher(plan,{signal,onChild});this.ingest(plan,result);}
      catch(e){
        this.state=JSON.parse(snapshot);if(signal.aborted)return;
        if(sessionInvalid(e))throw Error('SHARED_SESSION_INVALID');
        const failed=latest?this.state.posts.latestScan:this.state[group];failed.failures++;
        failed.nextAt=Date.now()+Math.min(3600,300*2**Math.min(failed.failures,4))*1000;
        if (plan.kind === 'highlight') {
          const entry=failed.todo.find(h=>h.id===plan.id);
          entry.failures=(entry.failures||0)+1;
          entry.retryAt=Date.now()+Math.min(3600,300*2**Math.min(entry.failures,4))*1000;
          failed.nextAt=0;
        }
        this.persist();this.log('CATALOG_CHECK_FAILED',{group,scope,reason:safeReason(e)});continue;
      }
      this.persist();this.log('CATALOG_CHECK_OK',{group,scope,kind:plan.kind,baselineComplete:this.state[group].baseline});
      if(group==='posts'&&!latest&&plan.cursor===null)this.log('CATALOG_CHECK_OK',{group,scope:'posts:latest',kind:plan.kind,baselineComplete:this.state.posts.baseline});
    }
  }
  async deliver(signal,sendTelegram,{shouldYield=()=>false}={}) {
    const started=Date.now();let ok=true,sends=0,tgBlocked=false;
    try { if (!(await fsp.stat(this.root)).isDirectory()) throw Error('CATALOG_ROOT_NOT_DIRECTORY'); }
    catch(e) { this.log('CATALOG_STORAGE_ERROR',{reason:safeReason(e)}); return false; }
    this.log('CATALOG_STORAGE_OK');
    this.asyncStore ||= new AtomicStateStore({file:this.file,initial:this.state});
    const progress=new ArchiveProgress({commit:()=>this.persistAsync()});
    const captions=[];
    for(const [id,caption] of Object.entries(this.state.captions).filter(([,c])=>c.savedHash!==c.hash).sort(([,a],[,b])=>(a.lastAttemptAt||0)-(b.lastAttemptAt||0)).slice(0,10)) {
      if(signal.aborted||shouldYield())break;
      caption.lastAttemptAt=Date.now();
      try {
        const file=this.full(caption.file);await fsp.mkdir(path.dirname(file),{recursive:true});
        const temp=file+'.part';await fsp.writeFile(temp,caption.text,{mode:0o644});
        const handle=await fsp.open(temp,'r+');try{await handle.sync();}finally{await handle.close();}
        await fsp.rename(temp,file);caption.savedHash=caption.hash;
      }catch(e){ok=false;await this.persistAsync();this.log('CATALOG_CAPTION_RETRY',{id,reason:archiveReason(e)});continue;}
      const completion=progress.complete('caption:'+id,{}).then(()=>this.log('CATALOG_CAPTION_SAVED',{id}));void completion.catch(()=>{});captions.push(completion);
    }
    await Promise.all([...captions,progress.flush()]);
    const pending=Object.values(this.state.assets).filter(a=>!a.archiveDone||!a.telegramDone).sort((a,b)=>(a.lastAttemptAt||0)-(b.lastAttemptAt||0));
    await archiveBatch(pending.filter(asset=>!asset.archiveDone),async asset=>{
      this.log('CATALOG_MEDIA_STARTED',{key:asset.key});
      let saved;
      try{saved=await this.downloader(this.root,asset.base,asset,{signal,timeoutMs:45000});}
      catch(e){if(signal.aborted||shouldYield())return;ok=false;asset.lastAttemptAt=Date.now();this.log('CATALOG_ARCHIVE_RETRY',{key:asset.key,reason:archiveReason(e)});}
      if(saved){asset.archiveDone=true;asset.relativePath=saved.relativePath;asset.bytes=saved.bytes;await progress.complete(asset.key,{});this.log('CATALOG_MEDIA_SAVED',{key:asset.key,path:saved.relativePath,bytes:saved.bytes});}
    },{signal,shouldYield,concurrency:archiveLimits().downloadConcurrency});
    await progress.flush();
    const groups=[],posts=new Map();
    for(const asset of pending.filter(a=>!a.telegramDone)) {
      if(asset.kind!=='post'){groups.push([asset]);continue;}
      if(!posts.has(asset.parent)){const group=[];posts.set(asset.parent,group);groups.push(group);}
      posts.get(asset.parent).push(asset);
    }
    groups.sort((a,b)=>(this.state.posts.records[a[0].parent]?.index??Infinity)-(this.state.posts.records[b[0].parent]?.index??Infinity));
    for(const group of groups) {
      const first=group[0];
      if(first.kind==='post')group.sort((a,b)=>this.state.posts.records[a.parent].parts[a.id]-this.state.posts.records[b.parent].parts[b.id]);
      for(let offset=0;offset<group.length;offset+=10) {
        if(signal.aborted||shouldYield()||Date.now()-started>=90000||tgBlocked||sends>=5)break;
        const batch=group.slice(offset,offset+10),asset=batch[0];
        const label=asset.kind==='post'?'IG 新貼文':`IG 精選：${asset.title}`;
        const text=asset.kind==='post'?this.state.captions[asset.parent]?.text||'':'';
        const caption=[`@${this.username}`,label,dateJST(asset.takenAt),asset.code?`https://www.instagram.com/p/${asset.code}/`:'',text].filter(Boolean).join('\n');
        const captionSent=asset.kind==='post'&&Object.values(this.state.assets).some(a=>a.kind==='post'&&a.parent===asset.parent&&a.telegramDone);
        const media=batch.map((a,index)=>({type:a.mediaType===2?'video':'photo',media:a.mediaUrl,
          ...(a.mediaType===2?{supports_streaming:true}:{}),...(!captionSent&&index===0?{caption:[...caption].slice(0,900).join('')}:{})}));
        const method=media.length>1?'sendMediaGroup':asset.mediaType===2?'sendVideo':'sendPhoto';
        const body=media.length>1?{media}:{[media[0].type]:media[0].media,...(media[0].caption!==undefined?{caption:media[0].caption}:{}),...(asset.mediaType===2?{supports_streaming:true}:{})};
        const ids=batch.map(a=>a.key),id=batch.length>1?`post:${asset.parent}:album:${batch.map(a=>a.id).join('-')}`:asset.key;
        for(const a of batch)this.log('CATALOG_TELEGRAM_STARTED',{key:a.key});
        let sent=false;sends++;
        try{await sendTelegram(method,body,{id,ids,...(asset.kind==='post'?{postId:asset.parent,postOrder:this.state.posts.records[asset.parent].parts[asset.id]}:{}),kind:asset.kind==='post'?'post':'highlight',detectedAt:Math.min(...batch.map(a=>a.detectedAt)),publishedAt:asset.takenAt*1000});sent=true;}
        catch(e){if(!e.message?.startsWith('TELEGRAM_'))throw e;ok=false;const reason=/^TELEGRAM_[A-Z0-9_]+$/.test(e.message)?e.message:'CATALOG_TELEGRAM_ERROR';for(const a of batch)this.log('CATALOG_TELEGRAM_RETRY',{key:a.key,reason});if(/_(401|403|429)$/.test(reason)||reason==='TELEGRAM_RETRY_WAIT')tgBlocked=true;}
        for(const a of batch){if(sent)a.telegramDone=true;a.lastAttemptAt=Date.now();}
        await this.persistAsync();
        if(sent)for(const a of batch)this.log('CATALOG_TELEGRAM_SENT',{key:a.key});
        // Keep a post's later chunks behind its failed chunk so captions and order stay stable.
        if(!sent)break;
      }
    }
    const pendingArchive=Object.values(this.state.assets).filter(a=>!a.archiveDone).length;
    const pendingTelegram=Object.values(this.state.assets).filter(a=>!a.telegramDone).length;
    const pendingCaptions=Object.values(this.state.captions).filter(c=>c.savedHash!==c.hash).length;
    this.log('CATALOG_STATUS',{posts:Object.keys(this.state.posts.records).length,highlights:Object.keys(this.state.highlights.records).length,pendingArchive,pendingTelegram,pendingCaptions,postsBaselineComplete:this.state.posts.baseline,highlightsBaselineComplete:this.state.highlights.baseline});
    return ok&&!pendingArchive&&!pendingTelegram&&!pendingCaptions&&!this.state.posts.failures&&!this.state.posts.latestScan.failures&&!this.state.highlights.failures&&!this.state.highlights.todo.some(h=>h.failures);
  }
}
