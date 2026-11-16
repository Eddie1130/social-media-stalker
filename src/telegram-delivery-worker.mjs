import {prepareUploads} from './telegram-upload.mjs';
import {eligibilityFingerprint} from './telegram-delivery-broker.mjs';
import {snapshot as metricsSnapshot} from './performance-metrics.mjs';
import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { PersonalDelivery } from './telegram-delivery.mjs';
import { ManualDelivery } from './manual-delivery.mjs';
import { XDelivery } from './x-delivery.mjs';
import { TikTokDelivery } from './tiktok-delivery.mjs';
import { describeUser } from './telegram-control.mjs';
import { eventDirectory } from './telegram-events.mjs';
import { load,log } from './error-monitor.mjs';
let settings,config,started=false,stopping=false,revision=0;
const pending=new Map();
const send=value=>{if(process.connected)process.send(value,()=>{});};
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const client={rate:{retryAt:0},baseUrl:'',async call(method,body,options={}){
 const requestId=randomUUID();let upload;
 try{
  upload=await prepareUploads(options.files||[],{dir:config.dir,requestId});
  if(stopping)throw Error('TELEGRAM_STOPPING');
  return await new Promise((resolve,reject)=>{
   pending.set(requestId,{resolve,reject,beforeRequest:options.beforeRequest});
   send({type:'request',requestId,revision,fingerprint:eligibilityFingerprint(settings,String(body.chat_id)),method,body,files:upload.files,timeoutMs:options.timeoutMs});
  });
 }finally{pending.delete(requestId);await upload?.cleanup();}
}};
process.on('message',async m=>{
 if(m.type==='settings'){
  settings=m.settings;revision=m.revision;config=m.config;client.baseUrl=config.baseUrl;
  if(!started){started=true;void run().catch(()=>{log('TELEGRAM_WORKER_FATAL',{reason:'WORKER_STATE_OR_IO_ERROR'});process.exitCode=1;process.disconnect();});}
 }else if(m.type==='prepare'){
  settings=m.settings;revision=m.revision;
  const job=pending.get(m.requestId);if(!job)return;
  try{await job.beforeRequest?.();send({type:'prepared',requestId:m.requestId,fingerprint:m.fingerprint});}
  catch(error){send({type:'prepared',requestId:m.requestId,fingerprint:m.fingerprint,error:/^(?:TELEGRAM_|X_DELIVERY_CANCELLED|MANUAL_DELIVERY_CANCELLED)/.test(error.message)?error.message:'TELEGRAM_BROKER_REQUEST_INVALID'});}
 }else if(m.type==='result'){
  const job=pending.get(m.requestId);if(!job)return;
  client.rate.retryAt=Math.max(client.rate.retryAt,m.retryAt||0);
  if(m.error)job.reject(Object.assign(Error(m.error),{messageUnavailable:m.messageUnavailable}));else job.resolve(m.result);
 }else if(m.type==='stop'){stopping=true;}
});
process.on('disconnect',()=>{stopping=true;for(const job of pending.values())job.reject(Error('TELEGRAM_NETWORK_OR_RESPONSE_ERROR'));});
process.on('SIGTERM',()=>{stopping=true;for(const job of pending.values())job.reject(Error('TELEGRAM_NETWORK_OR_RESPONSE_ERROR'));});
async function run(){
 const options={dir:config.dir,stateDir:config.stateDir,root:config.root,settings:()=>settings,log};
 const personal=new PersonalDelivery(options),manual=new ManualDelivery(options),x=config.xEnabled?new XDelivery(options):null,tt=new TikTokDelivery(options);
 const ok={personal:true,x:true,notice:true,video:true,content:true,story:true};
 const loop=async(name,work)=>{while(!stopping){ok[name]=await work();send({type:'health',health:{ready:true,telegramOk:Object.values(ok).every(Boolean),pending:Object.keys(personal.state.pending).length,performance:metricsSnapshot()}});await wait(1000);}};
 await Promise.all([
  loop('personal',async()=>{
   const events=eventDirectory(process.env);fs.mkdirSync(events,{recursive:true});
   const names=fs.readdirSync(events).filter(n=>/^[a-f0-9]{64}\.json$/.test(n)).slice(0,100);
   const rows=names.map(n=>({file:path.join(events,n),event:load(path.join(events,n),null)})).sort((a,b)=>a.event?.at-b.event?.at);
   for(const row of rows){personal.ingest(row.event);fs.unlinkSync(row.file);}
   personal.daily(Date.now(),id=>describeUser(settings,id,config.stateDir,config.watchdogDir));
   return personal.drain(client,{stopping:()=>stopping});
  }),loop('manual',async()=>{await manual.drain(client,{stopping:()=>stopping});return true;}),
  ...(x?[loop('x',()=>x.drain(client,{stopping:()=>stopping}))]:[]),
  ...['notice','video','content','story'].map(lane=>loop(lane,()=>tt.drain(client,{stopping:()=>stopping,lane})))
 ]);
 if(process.connected)process.disconnect();
}
