import sys,time,unittest,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tiktok'))
from catalog_query import BrowserWorker
class QueryTests(unittest.TestCase):
 def test_waiting_query_pumps_other_work_and_returns_only_matching_request(self):
  command=[sys.executable,'-u','-c','import sys,json,time\nfor l in sys.stdin:\n d=json.loads(l);time.sleep(.1);print(json.dumps({"requestId":d["requestId"],"epoch":d["epoch"],"result":{"ok":True}}),flush=True)']
  ticks=[];w=BrowserWorker(command=command,pump=lambda:ticks.append(1),timeout=2)
  try:self.assertEqual(w('alice','post'),{'ok':True});self.assertGreater(len(ticks),0)
  finally:w.close()
 def test_hung_query_has_finite_deadline_and_can_restart(self):
  w=BrowserWorker(command=[sys.executable,'-u','-c','import time;time.sleep(5)'],timeout=.1)
  try:
   with self.assertRaisesRegex(RuntimeError,'TIMEOUT'):w('alice','post')
   self.assertIsNone(w.proc)
  finally:w.close()

from catalog_scheduler import ArchiveCoordinator
import test_tiktok_catalog as fixture_module
from catalog_worker import STOP
class CoordinatorTests(unittest.TestCase):
 def setUp(self):
  self.fixture=fixture_module.CatalogTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
 def test_media_completion_is_checkpointed_without_a_poll_cycle(self):
  f=self.fixture;f.fetch.return_value=f.page(rows=[f.row(str(i)) for i in range(1,7)]);f.catalog.poll('alice','post',f.settings)
  c=ArchiveCoordinator(f.catalog,STOP)
  try:
   deadline=time.monotonic()+3
   while time.monotonic()<deadline and any(r['status']=='pending' for r in f.records()):c.pump(f.settings);time.sleep(.01)
   self.assertTrue(all(r['status']=='ready' for r in f.records()))
  finally:c.close(f.settings)

import threading
from unittest.mock import patch
class InterleavingTests(unittest.TestCase):
 def setUp(self):
  self.f=fixture_module.CatalogTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
 def test_finished_download_preserves_new_generation_and_caption(self):
  f=self.f;f.fetch.return_value=f.page(kind='story');f.catalog.poll('alice','story',f.settings)
  entered=threading.Event();release=threading.Event();original=f.download.side_effect
  def slow(*a,**k):entered.set();release.wait(3);return original(*a,**k)
  f.download.side_effect=slow;c=ArchiveCoordinator(f.catalog,STOP)
  try:
   c.pump(f.settings);self.assertTrue(entered.wait(1));f.time+=120001;f.settings['users']['100']['tiktokTargets']['alice']['generation']='new-generation'
   f.fetch.return_value=f.page(kind='story',rows=[f.row(caption='new caption')]);f.catalog.poll('alice','story',f.settings)
   before=f.records()[0];self.assertTrue(before.get('extraRecipients'))
   f.catalog.db.execute("UPDATE items SET data=json_set(data,'$.item.caption',?) WHERE kind='story'",('edited while downloading',));f.catalog.db.commit()
   release.set();deadline=time.monotonic()+2
   while c.active and time.monotonic()<deadline:c.pump(f.settings);time.sleep(.01)
   after=f.records()[0];self.assertEqual(after['observedGenerations']['100'],'new-generation')
   events=[json.loads(s) for s, in f.catalog.db.execute('SELECT data FROM outbox')]
   self.assertTrue(any(r.get('generation')=='new-generation' for e in events for r in e.get('recipients',[])))
   self.assertEqual((f.catalog.root/'tiktok/alice/stories/1/caption.txt').read_text(),'edited while downloading')
  finally:release.set();c.close(f.settings)
 def test_failed_checkpoint_keeps_completion_replayable(self):
  f=self.f;f.fetch.return_value=f.page();f.catalog.poll('alice','post',f.settings);c=ArchiveCoordinator(f.catalog,STOP)
  try:
   c.pump(f.settings)
   for future in c.active:future.result(timeout=2)
   with patch.object(f.catalog,'finish_archive',side_effect=RuntimeError('SQLITE_BUSY')):
    with self.assertRaises(RuntimeError):c.pump(f.settings)
   self.assertEqual(len(c.active),1)
   c.pump(f.settings);self.assertEqual(f.records()[0]['status'],'ready');self.assertFalse(c.busy)
  finally:c.close(f.settings)
 def test_stop_cancels_query_before_grace_period(self):
  stop=threading.Event();w=BrowserWorker(command=[sys.executable,'-u','-c','import time;time.sleep(5)'],timeout=3,stop=stop)
  timer=threading.Timer(.05,stop.set);timer.start();started=time.monotonic()
  try:
   with self.assertRaisesRegex(RuntimeError,'STOPPING'):w('alice','post')
   self.assertLess(time.monotonic()-started,1)
  finally:timer.cancel();w.close()

class WarmBrowserTests(unittest.TestCase):
 def test_same_account_requests_keep_warm_browser_until_idle(self):
  import os,io
  from catalog_browser_worker import serve
  class Session:
   def __init__(self):self.name=None;self.navigations=0;self.manual_required=False
   def __call__(self,name,*args):
    if self.name!=name:self.navigations+=1;self.name=name
    return {'ok':True}
   def idle(self):self.name=None
   def close(self):pass
  r,w=os.pipe();reader=os.fdopen(r);writer=os.fdopen(w,'w');output=io.StringIO();session=Session()
  thread=threading.Thread(target=serve,args=(reader,output,session,.3));thread.start()
  try:
   for i in range(2):
    writer.write(json.dumps({'requestId':str(i),'epoch':'one','name':'alice','kind':'post'})+'\n');writer.flush()
    deadline=time.monotonic()+1
    while output.getvalue().count('\n')<=i and time.monotonic()<deadline:time.sleep(.01)
   self.assertEqual(session.navigations,1)
  finally:writer.close();thread.join(timeout=2);reader.close()
