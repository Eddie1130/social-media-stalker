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
 def test_empty_retry_bounded_and_captcha_not_retried(self):
  s=SessionProvider()
  with patch.object(s,'_query',side_effect=[RuntimeError('TIKTOK_EMPTY_RESPONSE'),{'ok':True}]) as q,patch('catalog_worker.time.sleep'):
   self.assertEqual(s('alice','post'),{'ok':True});self.assertEqual(q.call_count,2)
  with patch.object(s,'_query',side_effect=RuntimeError('TIKTOK_CAPTCHA_REQUIRED')) as q:
   with self.assertRaises(RuntimeError):s('alice','post')
   self.assertEqual(q.call_count,1)

import test_tiktok_catalog as fixture_module
class RateLimitTests(unittest.TestCase):
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
