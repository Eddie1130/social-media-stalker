"""Bounded, private aggregate metrics; never retain request payloads."""
import math,threading
from functools import wraps
def synchronized(fn):
    @wraps(fn)
    def wrapped(self,*args,**kwargs):
        with self.lock:return fn(self,*args,**kwargs)
    return wrapped
NAMES=set('settings_commit event_loop api_slot api_http reply_queue reply_total browser_query browser_navigation browser_restart media_download media_bytes media_fsync queue_added queue_completed queue_failed'.split())
DIMENSIONS={'platform':('ig','x','tt'),'lane':('interactive','media','notice','story','video','content'),'kind':('post','repost','story','profile','like'),'outcome':('ok','error','retry','cancelled')}
BOUNDS=(1,5,10,25,50,100,250,500,1000,2000,5000,10000,30000,60000,180000,float('inf'))
class PerformanceMetrics:
    def __init__(self,max_series=128):
        self.max_series=max_series;self.data={};self.dropped=0;self.lock=threading.RLock()
    @synchronized
    def record(self,name,value,dimensions=None):
        tags=dimensions or {}
        if name not in NAMES or not math.isfinite(value) or any(v not in DIMENSIONS.get(k,()) for k,v in tags.items()):
            raise ValueError('INVALID_PERFORMANCE_METRIC')
        key=(name,tuple(sorted(tags.items())))
        if key not in self.data:
            if len(self.data)>=self.max_series:
                self.dropped+=1;return
            self.data[key]={'name':name,'dimensions':dict(key[1]),'count':0,'sum':0,'max':0,'buckets':[0]*len(BOUNDS)}
        row=self.data[key];value=max(0,value);row['count']+=1;row['sum']+=value;row['max']=max(row['max'],value)
        row['buckets'][next(i for i,b in enumerate(BOUNDS) if value<=b)]+=1
    @synchronized
    def snapshot(self):
        result=[]
        for row in self.data.values():
            item={k:v for k,v in row.items() if k!='buckets'}
            for label,p in [('p50',.5),('p95',.95)]:
                n=0
                for bound,count in zip(BOUNDS,row['buckets']):
                    n+=count
                    if n>=math.ceil(row['count']*p):item[label]=min(bound,row['max']);break
            result.append(item)
        return {'dropped':self.dropped,'series':result}
metrics=PerformanceMetrics()
record=metrics.record
snapshot=metrics.snapshot
