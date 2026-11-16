import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
export class PressureController {
 constructor(){this.level=3;this.high=0;this.low=0;}
 observe({checkpointP95Ms=0,eventLoopP95Ms=0,oldestInteractiveMs=0}){
  const high=checkpointP95Ms>500||eventLoopP95Ms>200||oldestInteractiveMs>1000;
  const low=checkpointP95Ms<250&&eventLoopP95Ms<100&&oldestInteractiveMs<500;
  this.high=high?this.high+1:0;this.low=low?this.low+1:0;
  if(this.high>=3){this.level=1;this.high=0;this.low=0;}
  else if(this.low>=6){this.level=Math.min(3,this.level+1);this.low=0;}
  return this.limits();
 }
 limits(){return {downloadConcurrency:this.level,allowHistoricalDiscovery:this.level===3};}
}
let cached={at:0,value:null,file:''};
export function archiveLimits({env=process.env,now=Date.now()}={}){
 if(env.ARCHIVE_PRESSURE_ENABLED!=='1')return {downloadConcurrency:3,allowHistoricalDiscovery:true};
 const file=path.join(env.IG_STATE_DIR||'/app/state','io-pressure.json');
 if(file!==cached.file||now-cached.at>5000){try{cached={file,at:now,value:JSON.parse(fs.readFileSync(file,'utf8'))};}catch{cached={file,at:now,value:null};}}
 const s=cached.value;
 if(!s||!Number.isFinite(s.at)||now-s.at>30000||now<s.at-5000||![1,2,3].includes(s.downloadConcurrency))return {downloadConcurrency:1,allowHistoricalDiscovery:false};
 return {downloadConcurrency:s.downloadConcurrency,allowHistoricalDiscovery:s.allowHistoricalDiscovery===true};
}
export function createPressurePublisher({stateDir,controlMetrics,readServiceMetrics,interactiveAge=()=>0,enabled=true}){
 if(!enabled)return {close(){}};
 const controller=new PressureController();let writing=false;
 const tick=async()=>{
  if(writing)return;writing=true;
  try{
   const local=controlMetrics(),remote=readServiceMetrics()||[];
   const rows=[...local.series,...remote.flatMap(m=>m?.series||[])];
   const checkpointP95Ms=Math.max(0,...rows.filter(r=>r.name==='settings_commit').map(r=>r.recentP95||r.p95||0));
   const eventLoopP95Ms=Math.max(0,...local.series.filter(r=>r.name==='event_loop').map(r=>r.last||0));
   const limits=controller.observe({checkpointP95Ms,eventLoopP95Ms,oldestInteractiveMs:interactiveAge()});
   const file=path.join(stateDir,'io-pressure.json'),tmp=file+'.'+process.pid+'.tmp';
   await fsp.writeFile(tmp,JSON.stringify({at:Date.now(),...limits}),{mode:0o600});await fsp.rename(tmp,file);
  }catch{/* Stale readers conservatively reduce background work. */}finally{writing=false;}
 };
 const timer=setInterval(()=>void tick(),5000);void tick();return {close(){clearInterval(timer);}};
}
