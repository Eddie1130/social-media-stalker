"""Single browser subprocess; the SQLite owner cooperatively pumps media IO."""
import json,os,queue,signal,subprocess,sys,threading,time,uuid
from pathlib import Path
MAX_MESSAGE=8*1024*1024
class BrowserWorker:
    def __init__(self,command=None,pump=None,timeout=None,stop=None):
        if timeout is None:
            timeout=float(os.getenv('TIKTOK_CATALOG_QUERY_TIMEOUT_SECONDS','180'))
            if not 30<=timeout<=600:raise ValueError('TIKTOK_INVALID_QUERY_TIMEOUT')
        self.command=command or [sys.executable,'-u',str(Path(__file__).with_name('catalog_browser_worker.py'))]
        self.pump=pump or (lambda:None);self.timeout=timeout;self.stop=stop;self.proc=None;self.epoch=None;self.results=queue.Queue(maxsize=8);self.manual_required=False;self.pending=None
    def _start(self):
        self.epoch=uuid.uuid4().hex;self.results=queue.Queue(maxsize=8)
        self.proc=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,start_new_session=True)
        output=self.proc.stdout;results=self.results
        def read():
            try:
                while True:
                    line=output.readline(MAX_MESSAGE+1)
                    if not line:break
                    if len(line)>MAX_MESSAGE:break
                    value=json.loads(line)
                    results.put(value,timeout=1)
            except Exception:pass
            finally:
                try:results.put({'workerClosed':True},timeout=.1)
                except queue.Full:pass
        threading.Thread(target=read,daemon=True).start()
    def submit(self,name,kind,cursor='0',item_id=None):
        if self.pending:raise RuntimeError('TIKTOK_QUERY_ALREADY_PENDING')
        if self.proc is None:self._start()
        rid=uuid.uuid4().hex
        job={'requestId':rid,'epoch':self.epoch,'name':name,'kind':kind,'cursor':cursor,'itemId':item_id}
        try:self.proc.stdin.write(json.dumps(job)+'\n');self.proc.stdin.flush()
        except (BrokenPipeError,OSError):self.close();raise RuntimeError('TIKTOK_BROWSER_TRANSPORT_FAILED') from None
        self.pending=rid
        return rid
    def poll_results(self):
        rows=[]
        while True:
            try:rows.append(self.results.get_nowait())
            except queue.Empty:return rows
    def __call__(self,name,kind,cursor='0',item_id=None):
        rid=self.submit(name,kind,cursor,item_id);deadline=time.monotonic()+self.timeout
        try:
            while time.monotonic()<deadline:
                if self.stop and self.stop.is_set():
                    self.close();raise RuntimeError('TIKTOK_STOPPING')
                self.pump()
                try:row=self.results.get(timeout=.05)
                except queue.Empty:continue
                if row.get('workerClosed'):
                    self.close();raise RuntimeError('TIKTOK_BROWSER_TRANSPORT_FAILED')
                if row.get('requestId')!=rid or row.get('epoch')!=self.epoch:continue
                self.manual_required=row.get('manualRequired',False)
                if row.get('error'):
                    error=RuntimeError(row['error']);retry=row.get('retryAfter')
                    if isinstance(retry,(int,float)) and 0<retry<=604800:error.retry_after=retry
                    raise error
                return row['result']
            self.close();raise RuntimeError('TIKTOK_BROWSER_QUERY_TIMEOUT')
        finally:self.pending=None
    def idle(self):pass
    def close(self):
        proc=self.proc;self.proc=None;self.pending=None
        if not proc:return
        try:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)
        except ProcessLookupError:pass
        finally:
            for f in (proc.stdin,proc.stdout):
                if f:f.close()
