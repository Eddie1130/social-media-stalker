import { fork } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import { openAsBlob } from 'node:fs';
import path from 'node:path';
const methods=new Set(['sendMessage','sendPhoto','sendVideo','sendDocument','sendMediaGroup','deleteMessage','editMessageText']);
export function eligibilityFingerprint(settings,id){return createHash('sha256').update(JSON.stringify([settings.ownerId,settings.allowedIds.includes(id),settings.users[id]])).digest('hex');}
export function validateBrokerRequest(request,settings){
 if(!methods.has(request.method)||!request.body||!settings.allowedIds.includes(String(request.body.chat_id))||JSON.stringify(request.body).length>2*1024*1024)throw Error('TELEGRAM_BROKER_REQUEST_INVALID');
 if(request.files&&!Array.isArray(request.files))throw Error('TELEGRAM_BROKER_REQUEST_INVALID');
}
export async function validateBrokerFiles(body,roots){
 const links=[];
 const walk=(value,key='')=>{if(typeof value==='string'&&['video','photo','document','thumbnail','media'].includes(key)&&value.startsWith('file:'))links.push(value);else if(Array.isArray(value))value.forEach(x=>walk(x,key));else if(value&&typeof value==='object')Object.entries(value).forEach(([k,v])=>walk(v,k));};
 walk(body);if(links.length>32)throw Error('TELEGRAM_BROKER_REQUEST_INVALID');
 const allowed=await Promise.all(roots.map(async root=>{try{return await fs.realpath(root);}catch{return null;}}));
 for(const link of links){const file=await fs.realpath(fileURLToPath(link));if(!allowed.some(root=>root&&file.startsWith(root+path.sep))||!(await fs.stat(file)).isFile())throw Error('TELEGRAM_BROKER_REQUEST_INVALID');}
}
export const validAttachmentName=name=>typeof name==='string'&&/^(?:thumbnail|photo|video|document|media[0-9]|thumb[0-9]|cover[0-9])$/.test(name);
export function deliveryWorkerEnv(env,baseUrl){
 const result=Object.fromEntries(['PATH','TZ','ARCHIVE_PRESSURE_ENABLED','IG_CONTROL_DIR','IG_STATE_DIR','IG_ARCHIVE_DIR','IG_WATCHDOG_DIR','X_ENABLED'].filter(k=>env[k]!==undefined).map(k=>[k,env[k]]));
 if(baseUrl)result.TELEGRAM_BOT_API_URL=baseUrl;
 return result;
}
export class DeliveryBroker {
 constructor({client,settings,env=process.env,child,log=()=>{}}){
  Object.assign(this,{client,settings,env,log});this.requests=new Map();this.stopping=false;this.revision=0;this.health={telegramOk:true,ready:false};
  const workerEnv=deliveryWorkerEnv(env,client.baseUrl);
  this.spawn=()=>fork(new URL('./telegram-delivery-worker.mjs',import.meta.url),[],{env:workerEnv,stdio:['ignore','inherit','inherit','ipc']});
  this.child=child||this.spawn();
  this.attach();
  this.update(settings());
 }
 attach(){
  this.child.on('message',m=>{void this.message(m).catch(()=>this.log('TELEGRAM_WORKER_PROTOCOL_FAILED',{reason:'WORKER_PROTOCOL_ERROR'}));});
  this.child.on('exit',()=>{this.health={telegramOk:false,ready:false};for(const job of this.requests.values())job.reject?.(Error('TELEGRAM_NETWORK_OR_RESPONSE_ERROR'));this.requests.clear();if(!this.stopping){this.log('TELEGRAM_WORKER_RESTART',{reason:'WORKER_EXIT'});this.restartTimer=setTimeout(()=>{if(!this.stopping){this.child=this.spawn();this.attach();this.update(this.settings());}},3000);}});
 }
 send(message){if(this.child.connected!==false)this.child.send(message,()=>{});}
 update(settings){this.revision++;this.send({type:'settings',revision:this.revision,settings,config:{baseUrl:this.client.baseUrl,dir:this.env.IG_CONTROL_DIR||'/app/control',stateDir:this.env.IG_STATE_DIR||'/app/state',root:this.env.IG_ARCHIVE_DIR||'/downloads',watchdogDir:this.env.IG_WATCHDOG_DIR||'/app/watchdog-state',xEnabled:this.env.X_ENABLED!=='0'}});}
 async message(m){
  if(m?.type==='health'){this.health=m.health;return;}
  if(m?.type==='prepared'){
   const job=this.requests.get(m.requestId);if(job?.resolve)job.resolve(m);return;
  }
  if(m?.type!=='request')return;
  if(this.stopping||this.requests.size>=32){this.send({type:'result',requestId:m.requestId,error:'TELEGRAM_RETRY_WAIT'});return;}
  if(typeof m.requestId!=='string'||!/^[a-f0-9-]{36}$/.test(m.requestId)||this.requests.has(m.requestId))return;
  const job={};this.requests.set(m.requestId,job);
  try{
   validateBrokerRequest(m,this.settings());
   await validateBrokerFiles(m.body,[this.env.IG_ARCHIVE_DIR||'/downloads',path.join(this.env.IG_CONTROL_DIR||'/app/control','.broker-upload')]);
   const files=[];
   for(const descriptor of m.files||[]){
    const spool=await fs.realpath(descriptor.source===true?(this.env.IG_ARCHIVE_DIR||'/downloads'):path.join(this.env.IG_CONTROL_DIR||'/app/control','.broker-upload'));
    const file=await fs.realpath(descriptor.path);
    if(!file.startsWith(spool+path.sep)||!(await fs.stat(file)).isFile()||!validAttachmentName(descriptor.name)||typeof descriptor.filename!=='string'||descriptor.filename.length>255)throw Error('TELEGRAM_BROKER_REQUEST_INVALID');
    files.push({name:descriptor.name,filename:descriptor.filename,blob:await openAsBlob(file,{type:descriptor.type||'application/octet-stream'})});
   }
   let prepared;
   const result=await this.client.call(m.method,m.body,{files,timeoutMs:m.timeoutMs,prepareRequest:async()=>{
    const snapshot=this.settings(),fingerprint=eligibilityFingerprint(snapshot,String(m.body.chat_id));
    if(m.fingerprint&&m.fingerprint!==fingerprint)throw Error('TELEGRAM_RETRY_WAIT');
    prepared=await new Promise((resolve,reject)=>{
     const timer=setTimeout(()=>reject(Error('TELEGRAM_NETWORK_OR_RESPONSE_ERROR')),15000);
     job.resolve=value=>{clearTimeout(timer);resolve(value);};job.reject=error=>{clearTimeout(timer);reject(error);};
     this.send({type:'prepare',requestId:m.requestId,settings:snapshot,revision:this.revision,fingerprint});
    });
    if(prepared.error)throw Error(prepared.error);
    if(prepared.fingerprint!==fingerprint)throw Error('TELEGRAM_RETRY_WAIT');
   },beforeSend:()=>{
    validateBrokerRequest(m,this.settings());
    if(prepared.fingerprint!==eligibilityFingerprint(this.settings(),String(m.body.chat_id)))throw Error('TELEGRAM_RETRY_WAIT');
   }});
   this.send({type:'result',requestId:m.requestId,result});
  }catch(error){
   const message=/^(?:TELEGRAM_(?:ERROR_\d+|NETWORK_OR_RESPONSE_ERROR|RETRY_WAIT|STOPPING)|X_DELIVERY_CANCELLED|MANUAL_DELIVERY_CANCELLED)$/.test(error.message)?error.message:'TELEGRAM_BROKER_REQUEST_INVALID';
   this.send({type:'result',requestId:m.requestId,error:message,retryAt:this.client.rate?.retryAt||0,messageUnavailable:!!error.messageUnavailable});
  }finally{this.requests.delete(m.requestId);}
 }
 async stop(){
  this.stopping=true;clearTimeout(this.restartTimer);this.send({type:'stop'});
  if(this.child.exitCode!==null&&this.child.exitCode!==undefined)return;
  await new Promise(resolve=>{const timer=setTimeout(()=>{this.child.kill('SIGTERM');resolve();},20000);this.child.once('exit',()=>{clearTimeout(timer);resolve();});});
 }
}
