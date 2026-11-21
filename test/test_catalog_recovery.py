import sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tiktok'))
from catalog_worker import SessionProvider
from catalog_errors import classify_failure
class RecoveryTests(unittest.TestCase):
 def test_idle_browser_failure_is_local(self):
  s=SessionProvider();s.browser=Mock();s.name='alice';s.browser.park.side_effect=RuntimeError('closed')
  s.idle();self.assertIsNone(s.browser);self.assertFalse(s.manual_required)
 def test_classification_never_marks_empty_as_success(self):
  self.assertEqual(classify_failure(RuntimeError('TIKTOK_EMPTY_RESPONSE')).category,'empty_response')
  self.assertEqual(classify_failure(RuntimeError('TIKTOK_CAPTCHA_REQUIRED')).category,'captcha')
  self.assertFalse(classify_failure(RuntimeError('TIKTOK_CAPTCHA_REQUIRED')).retryable)
 def test_scheduled_post_empty_response_waits_for_next_poll(self):
  session=SessionProvider()
  with patch('catalog_worker.POST_POLL_TEST_INTERVAL',0), patch.object(
   session,'_query',side_effect=RuntimeError('TIKTOK_EMPTY_RESPONSE')
  ) as query, patch('catalog_worker.time.sleep') as delay:
   with self.assertRaisesRegex(RuntimeError,'TIKTOK_EMPTY_RESPONSE'):
    session('alice','post')
   query.assert_called_once_with('alice','post','0',None)
   delay.assert_not_called()

 def test_other_empty_retries_bounded_and_captcha_not_retried(self):
  s=SessionProvider()
  for kind,item_id in (('story',None),('post','123')):
   with self.subTest(kind=kind,item_id=item_id), patch.object(
    s,'_query',side_effect=[RuntimeError('TIKTOK_EMPTY_RESPONSE'),{'ok':True}]
   ) as q, patch('catalog_worker.time.sleep'):
    self.assertEqual(s('alice',kind,item_id=item_id),{'ok':True})
    self.assertEqual(q.call_count,2)
  with patch.object(s,'_query',side_effect=RuntimeError('TIKTOK_CAPTCHA_REQUIRED')) as q:
   with self.assertRaises(RuntimeError):s('alice','post')
   self.assertEqual(q.call_count,1)

import test_tiktok_catalog as fixture_module
class RateLimitTests(unittest.TestCase):
 def test_post_cooldown_is_global_and_leaves_other_streams_eligible(self):
  import copy
  from catalog_scheduler import select_stream
  f=fixture_module.CatalogTests();f.setUp();self.addCleanup(f.doCleanups)
  for user in f.settings['users'].values():
   user['tiktokTargets']['bob']=copy.deepcopy(user['tiktokTargets']['alice'])
  for name in ('alice','bob'):
   for kind in ('story','post','repost','profile'):
    state=f.catalog.stream(name,kind)
    state.update(baseline=True,nextAt=0 if kind=='post' or (name,kind)==('alice','repost') else 999999)
    f.catalog.save_stream(name,kind,state)
  f.catalog.db.commit()

  def fetch(name,kind,cursor):
   if (name,kind)==('alice','post'):
    f.time+=15000
    raise RuntimeError('TIKTOK_EMPTY_RESPONSE')
   return {**f.page(kind,rows=[]), 'username':name}

  f.fetch.side_effect=fetch
  with patch('catalog_worker.POST_REQUEST_GAP_MS',120000,create=True):
   f.catalog.poll('alice','post',f.settings)
   deadline=f.time+120000
   f.catalog.poll('bob','post',f.settings)
   self.assertEqual(f.fetch.call_count,1)
   self.assertEqual(select_stream(f.catalog,f.settings,f.time),('alice','repost'))
   f.catalog.poll('alice','repost',f.settings)
   f.time=deadline-1
   f.catalog.poll('bob','post',f.settings)
   self.assertEqual(f.fetch.call_count,2)
   f.time=deadline
   self.assertEqual(select_stream(f.catalog,f.settings,f.time),('bob','post'))
   f.catalog.poll('bob','post',f.settings)
   self.assertEqual(f.fetch.call_count,3)

 def test_server_retry_after_is_not_shortened_by_local_backoff(self):
  f=fixture_module.CatalogTests();f.setUp();self.addCleanup(f.doCleanups)
  error=RuntimeError('TIKTOK_RATE_LIMITED');error.retry_after=300
  f.fetch.side_effect=error;f.catalog.poll('alice','post',f.settings)
  self.assertGreaterEqual(f.catalog.stream('alice','post')['nextAt'],f.time+300000)

class DiagnosticTests(unittest.TestCase):
 def test_child_diagnostic_preserves_location_without_exception_payload(self):
  from catalog_errors import safe_diagnostic
  import json
  try:raise ValueError('private-cookie https://private.example net::ERR_CONNECTION_RESET')
  except ValueError as error:diagnostic=safe_diagnostic(error)
  self.assertEqual(diagnostic['exception'],'ValueError')
  self.assertEqual(diagnostic['networkError'],'ERR_CONNECTION_RESET')
  self.assertEqual(diagnostic['frames'][-1]['function'],'test_child_diagnostic_preserves_location_without_exception_payload')
  self.assertNotIn('private-cookie',json.dumps(diagnostic))
  self.assertNotIn('https://',json.dumps(diagnostic))

class HeartbeatTests(unittest.TestCase):
 def test_failed_heartbeat_reports_safe_cause_and_stops_owner(self):
  import contextlib,io,json,errno
  from catalog_worker import heartbeat_loop
  stop=Mock();stop.wait.return_value=False
  catalog=Mock();error=OSError(errno.ENOSPC,'private-cookie-secret')
  catalog.heartbeat.side_effect=error
  errors=[];output=io.StringIO()
  with contextlib.redirect_stdout(output):heartbeat_loop(catalog,stop,errors,interval=0)
  stop.set.assert_called_once();self.assertEqual(errors,[error])
  row=json.loads(output.getvalue())
  self.assertEqual(row['event'],'TIKTOK_CATALOG_HEARTBEAT_FAILED')
  self.assertEqual(row['failureCode'],'TIKTOK_STORAGE_FAILED')
  self.assertEqual(row['errno'],errno.ENOSPC)
  self.assertNotIn('private-cookie-secret',output.getvalue())

 def test_broken_log_pipe_cannot_disable_heartbeat_failure_shutdown(self):
  from catalog_worker import heartbeat_loop
  stop=Mock();stop.wait.return_value=False
  catalog=Mock();catalog.heartbeat.side_effect=OSError('private-error')
  errors=[]
  with patch('builtins.print',side_effect=BrokenPipeError):heartbeat_loop(catalog,stop,errors,interval=0)
  stop.set.assert_called_once();self.assertEqual(len(errors),1)
