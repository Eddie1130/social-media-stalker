"""Shared, rebuildable I/O pressure summary; no durable task data."""
import json,os,time
from pathlib import Path
class PressureController:
    def __init__(self):self.level=3;self.high=0;self.low=0
    def observe(self,s):
        a,b,c=(s.get(k,0) for k in ('checkpointP95Ms','eventLoopP95Ms','oldestInteractiveMs'))
        self.high=self.high+1 if a>500 or b>200 or c>1000 else 0
        self.low=self.low+1 if a<250 and b<100 and c<500 else 0
        if self.high>=3:self.level=1;self.high=self.low=0
        elif self.low>=6:self.level=min(3,self.level+1);self.low=0
        return self.limits()
    def limits(self):return {'downloadConcurrency':self.level,'allowHistoricalDiscovery':self.level==3}
_cache={'at':0,'file':None,'value':None}
def archive_limits(state_dir):
    if os.getenv('ARCHIVE_PRESSURE_ENABLED')!='1':return {'downloadConcurrency':3,'allowHistoricalDiscovery':True}
    now=time.time();file=Path(state_dir)/'io-pressure.json'
    if _cache['file']!=file or now-_cache['at']>5:
        try:value=json.loads(file.read_text())
        except (OSError,ValueError):value=None
        _cache.update(at=now,file=file,value=value)
    s=_cache['value']
    if not s or not isinstance(s.get('at'),(int,float)) or now*1000-s['at']>30000 or now*1000<s['at']-5000 or s.get('downloadConcurrency') not in (1,2,3):return {'downloadConcurrency':1,'allowHistoricalDiscovery':False}
    return {'downloadConcurrency':s['downloadConcurrency'],'allowHistoricalDiscovery':s.get('allowHistoricalDiscovery') is True}
