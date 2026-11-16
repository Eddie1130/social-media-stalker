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
