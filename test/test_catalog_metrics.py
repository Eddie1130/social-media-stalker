import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tiktok'))
from catalog_metrics import PerformanceMetrics
class MetricsTests(unittest.TestCase):
 def test_bounds_and_privacy(self):
  m=PerformanceMetrics(max_series=2);m.record('settings_commit',-4,{'outcome':'ok'});m.record('settings_commit',100,{'outcome':'ok'})
  self.assertEqual(m.snapshot()['series'][0]['count'],2)
  with self.assertRaises(ValueError):m.record('api_http',1,{'url':'private'})
  m.record('api_http',10);m.record('browser_query',20)
  self.assertEqual(len(m.snapshot()['series']),2);self.assertEqual(m.snapshot()['dropped'],1)
 def test_quantile(self):
  m=PerformanceMetrics()
  for i in range(100):m.record('api_http',i+1)
  self.assertEqual(m.snapshot()['series'][0]['p95'],100)

class ObserverTests(unittest.TestCase):
 def test_storage_blockage_is_visible_in_private_observation_summary(self):
  import importlib.util,json,tempfile,time
  script=Path(__file__).resolve().parents[1]/'scripts/collect-nas-performance.py'
  spec=importlib.util.spec_from_file_location('catalog_observer_fixture',script)
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  with tempfile.TemporaryDirectory() as folder:
   file=Path(folder)/'data/watch/tiktok/catalog/health.json';file.parent.mkdir(parents=True)
   file.write_text(json.dumps({'at':int(time.time()*1000),'phase':'running','storageBlocked':True,'targets':{}}))
   summary=module.collect(folder)['services']['tt']
   self.assertTrue(summary['storageBlocked'])
   self.assertNotIn('targets',summary)
