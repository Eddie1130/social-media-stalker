#!/usr/bin/env python3
"""Read-only bounded health sampler. Never calls Telegram or reads credentials."""
import argparse,json,pathlib,time,os

def collect(root):
    root=pathlib.Path(root)
    state=root/'state' if (root/'state').exists() else root/'data/watch'
    control=root/'control' if (root/'control').exists() else root/'data/control'
    result={'at':int(time.time()*1000),'load':list(os.getloadavg()),'services':{}}
    for name,file in [('telegram',control/'health.json'),('ig',state/'health.json'),('x',state/'x/health.json'),('tt',state/'tiktok/catalog/health.json')]:
        try:
            h=json.loads(file.read_text());s={k:h[k] for k in ('phase','failures','pollOk','telegramOk','pending','unresolved','manualRequired','performance') if k in h}
            s['ageMs']=result['at']-h.get('at',0)
            if name=='tt':s['streams']=[{'kind':k,'failures':v.get('consecutiveFailures',v.get('failures',0)),'ageMs':result['at']-v.get('lastSuccess',0)} for t in h.get('targets',{}).values() for k,v in t.items()]
            result['services'][name]=s
        except (OSError,ValueError):result['services'][name]={'readError':True}
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default='/app');p.add_argument('--interval',type=float,default=60);p.add_argument('--once',action='store_true');a=p.parse_args()
    while True:
        print(json.dumps(collect(a.root)),flush=True)
        if a.once:break
        time.sleep(max(1,a.interval))
