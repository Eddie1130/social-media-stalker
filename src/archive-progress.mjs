// Completion promises resolve only after their group is durably checkpointed.
export class ArchiveProgress {
  constructor({commit,maxItems=10,maxDelayMs=1000}) {Object.assign(this,{commit,maxItems,maxDelayMs});this.pending=[];this.tail=Promise.resolve();this.timer=null;}
  complete(key,patch) {
    const promise=new Promise((resolve,reject)=>this.pending.push({key,patch,resolve,reject}));
    if(this.pending.length>=this.maxItems)void this.flush().catch(()=>{});
    else if(!this.timer)this.timer=setTimeout(()=>{this.timer=null;void this.flush().catch(()=>{});},this.maxDelayMs);
    return promise;
  }
  flush() {
    if(this.timer){clearTimeout(this.timer);this.timer=null;}
    if(!this.pending.length)return this.tail;
    const batch=this.pending.splice(0);
    const run=async()=>{try{await this.commit(batch.map(({key,patch})=>({key,patch})));for(const item of batch)item.resolve();}catch(error){for(const item of batch)item.reject(error);throw error;}};
    this.tail=this.tail.then(run,run);void this.tail.catch(()=>{});return this.tail;
  }
}
