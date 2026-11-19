"""Private stdin/stdout protocol. Exactly one owner of the persistent profile."""
import json,os,re,select,signal,sys
from catalog_errors import classify_failure, safe_diagnostic

def serve(reader,writer,session,idle_seconds=1):
    try:
        while True:
            ready,_,_=select.select([reader],[],[],idle_seconds)
            if not ready:
                session.idle();continue
            line=reader.readline(65537)
            if not line:break
            if len(line)>65536:raise ValueError('TIKTOK_QUERY_TOO_LARGE')
            job=json.loads(line)
            if not re.fullmatch(r'[a-z0-9_][a-z0-9_.]{0,23}',str(job.get('name',''))) or job.get('kind') not in ('story','post','repost','profile','like'):raise ValueError('TIKTOK_QUERY_INVALID')
            row={'requestId':job['requestId'],'epoch':job['epoch']}
            try:row['result']=session(job['name'],job['kind'],job.get('cursor','0'),job.get('itemId'))
            except Exception as error:
                row['error']=classify_failure(error).safe_code
                row['diagnostic']=safe_diagnostic(error)
                retry=getattr(error,'retry_after',None)
                if isinstance(retry,(int,float)) and 0<retry<=604800:row['retryAfter']=retry
            row['manualRequired']=session.manual_required
            print(json.dumps(row),file=writer,flush=True)
    finally:session.close()

def main():
    os.environ['TIKTOK_BROWSER_CHILD_PROCESS']='1'
    from catalog_worker import SessionProvider
    def stop(*_):raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop)
    serve(sys.stdin,sys.stdout,SessionProvider())

if __name__=='__main__':main()
