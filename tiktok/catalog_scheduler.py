"""Media completion/checkpoint coordinator; all database calls stay on its owner."""
from concurrent.futures import ThreadPoolExecutor
import json,time,sqlite3
from contextlib import suppress
from catalog_layout import account_media
from catalog_pressure import archive_limits
from catalog_metrics import record
class ArchiveCoordinator:
    def __init__(self,catalog,stop,max_workers=3):
        self.catalog=catalog;self.stop=stop;self.pool=ThreadPoolExecutor(max_workers=max_workers,thread_name_prefix='tiktok-media');self.max_workers=max_workers;self.active={};self.busy=set();self.refresh=[];self.refreshing=set();self.last_scan=0;self.manual_count=0;self.closing=False
    def pump(self,settings):
        c=self.catalog
        for future in list(self.active):
            if future.done():
                job,key=self.active[future]
                if not future.cancelled():c.finish_archive(job,future,settings)
                self.active.pop(future);self.busy.discard(key)
                record('queue_completed',1,{'platform':'tt','outcome':'cancelled' if future.cancelled() else ('error' if future.exception() else 'ok')})
        if self.stop.is_set() or self.closing:return
        capacity=min(self.max_workers,archive_limits(c.state_dir)["downloadConcurrency"])
        if len(self.active)+self.manual_count>=capacity:return
        # Scan only when a slot is free, at most twice per second.
        now=time.monotonic()
        if now-self.last_scan<.5:return
        self.last_scan=now
        for target,kind,iid,data in c.ready_items('pending',__import__('worker').subscriptions(settings),50,stories_first=True):
            if len(self.active)+self.manual_count>=capacity:break
            r=json.loads(data);key=r['item']['id']
            if key in self.busy or (target,kind,iid) in self.refreshing:continue
            if r.get('failures') and kind!='profile' and not r.get('downloadRefreshed'):
                token=(target,kind,iid)
                if token not in self.refreshing:self.refreshing.add(token);self.refresh.append((target,kind,iid,r))
                continue
            folder=('manual/' if r.get('manual') else '')+r['folder']
            reusable=[account_media(c.root,c.db,folder,key,i) for i in range(1,len(r['item']['assets'])+1)]
            f=self.pool.submit(c.archive,r,reusable);self.active[f]=((target,kind,iid,r),key);self.busy.add(key)
    def archive_manual(self,r,settings):
        key=r['item']['id'];c=self.catalog
        while len(self.active)+self.manual_count>=self.max_workers or key in self.busy:
            if self.stop.is_set():raise RuntimeError('TIKTOK_DOWNLOAD_INTERRUPTED')
            self.pump(settings);time.sleep(.05)
        folder=('manual/' if r.get('manual') else '')+r['folder']
        reusable=[account_media(c.root,c.db,folder,key,i) for i in range(1,len(r['item']['assets'])+1)]
        self.manual_count+=1;self.busy.add(key)
        future=None
        try:
            future=self.pool.submit(c.archive,r,reusable)
            while not future.done():self.pump(settings);time.sleep(.05)
            return future.result()
        finally:
            try:
                # A cooperative DB failure must not release the per-item guard
                # while its manual download is still writing the same paths.
                if future is not None and not future.done() and not future.cancel():
                    with suppress(Exception):future.result()
            finally:
                self.manual_count-=1;self.busy.discard(key)
    def refresh_one(self,settings):
        if not self.refresh:return
        target,kind,iid,r=self.refresh.pop(0);c=self.catalog
        try:
            result=c.fetcher(r['username'],kind,'0',iid)['items'][0]
            if result['id']!=iid:raise RuntimeError('TIKTOK_ITEM_IDENTITY_INVALID')
            r['item']['assets']=result['assets'];r['downloadRefreshed']=True
            c.db.execute('UPDATE items SET data=? WHERE target=? AND kind=? AND id=?',(json.dumps(r),target,kind,iid));c.db.commit()
        except Exception as error:
            if isinstance(error,sqlite3.Error):raise
            if self.stop.is_set():
                c.db.rollback()
                return
            r['retryAt']=c.clock()+60000
            c.db.execute('UPDATE items SET data=? WHERE target=? AND kind=? AND id=?',(json.dumps(r),target,kind,iid));c.db.commit()
        finally:self.refreshing.discard((target,kind,iid))
    def close(self,settings):
        self.closing=True
        self.pool.shutdown(wait=True,cancel_futures=True)
        self.pump(settings)

def select_stream(catalog,settings,now):
    from worker import subscriptions
    priority={'story':0,'post':1,'repost':1,'profile':2,'like':3}
    due=[]
    pressure=archive_limits(catalog.state_dir)
    for name in subscriptions(settings):
        for kind in ('story','post','repost','profile','like'):
            if kind == 'post' and not catalog.post_poll_allowed(now):continue
            if not catalog.target_recipients(settings,name,kind):continue
            state=catalog.stream(name,kind)
            if state['nextAt']<=now:
                rank=priority[kind] if state.get('baseline') or kind=='story' else 4
                if rank==4 and not pressure['allowHistoricalDiscovery'] and now-getattr(catalog,'_last_history_query',0)<60000:continue
                due.append((rank,state['nextAt'],name,kind))
    if not due:return None
    # Oldest due work within a priority class; historical jobs age into fairness.
    overdue=[row for row in due if now-row[1]>600000 and row[1]>0]
    chosen=min(overdue or due,key=lambda x:(x[1],x[0]) if overdue else (x[0],x[1]))
    if chosen[0]==4:catalog._last_history_query=now
    return chosen[2],chosen[3]
