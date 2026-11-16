const names = new Set(['settings_commit','event_loop','api_slot','api_http','reply_queue','reply_total','browser_query','browser_navigation','browser_restart','media_download','media_bytes','media_fsync','queue_added','queue_completed','queue_failed']);
const dimensions = { platform:['ig','x','tt'], lane:['interactive','media','notice','story','video','content'], kind:['post','repost','story','profile','like'], outcome:['ok','error','retry','cancelled'] };
const bounds = [1,5,10,25,50,100,250,500,1000,2000,5000,10000,30000,60000,180000,Infinity];
export class PerformanceMetrics {
  constructor({maxSeries=128}={}) { this.maxSeries=maxSeries; this.data=new Map(); this.dropped=0; }
  record(name, value, tags={}) {
    if(!names.has(name)||!Number.isFinite(value)||Object.entries(tags).some(([k,v])=>!dimensions[k]?.includes(v))) throw Error('INVALID_PERFORMANCE_METRIC');
    const sorted=Object.fromEntries(Object.entries(tags).sort()); const key=JSON.stringify([name,sorted]);
    if(!this.data.has(key)) { if(this.data.size>=this.maxSeries){this.dropped++;return;}this.data.set(key,{name,dimensions:sorted,count:0,sum:0,max:0,last:0,recent:[],buckets:bounds.map(()=>0)}); }
    const row=this.data.get(key);value=Math.max(0,value);row.count++;row.last=value;row.recent.push(value);if(row.recent.length>32)row.recent.shift();row.sum+=value;row.max=Math.max(row.max,value);row.buckets[bounds.findIndex(b=>value<=b)]++;
  }
  snapshot() { return {dropped:this.dropped,series:[...this.data.values()].map(row=>{
    const percentile=p=>{let n=0;for(let i=0;i<bounds.length;i++){n+=row.buckets[i];if(n>=Math.ceil(row.count*p))return Math.min(bounds[i],row.max);}return 0;};
    return {name:row.name,dimensions:row.dimensions,count:row.count,sum:row.sum,max:row.max,last:row.last,recentP95:[...row.recent].sort((a,b)=>a-b)[Math.ceil(row.recent.length*.95)-1],p50:percentile(.5),p95:percentile(.95)};
  })}; }
}
export const metrics=new PerformanceMetrics();
export const record=(...args)=>metrics.record(...args);
export const snapshot=()=>metrics.snapshot();
