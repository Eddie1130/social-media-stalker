import sys,unittest,time,threading
from pathlib import Path
from unittest.mock import Mock,patch
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tiktok'))
from catalog_pressure import PressureController
class PressureTests(unittest.TestCase):
 def test_hysteresis_matches_js(self):
  p=PressureController()
  for _ in range(3):p.observe({'checkpointP95Ms':600,'eventLoopP95Ms':0,'oldestInteractiveMs':0})
  self.assertEqual(p.limits()['downloadConcurrency'],1)
  for _ in range(6):p.observe({'checkpointP95Ms':10,'eventLoopP95Ms':10,'oldestInteractiveMs':0})
  self.assertEqual(p.limits()['downloadConcurrency'],2)
  for _ in range(6):p.observe({'checkpointP95Ms':10,'eventLoopP95Ms':10,'oldestInteractiveMs':0})
  self.assertEqual(p.limits()['downloadConcurrency'],3)

from catalog_media import delivery_parts
class SplitTests(unittest.TestCase):
 def test_split_work_is_serial_and_stop_does_not_start_ffmpeg(self):
  file=Mock();file.suffix='.mp4';file.stat.return_value.st_size=2000
  active=[0,0];lock=threading.Lock()
  def split(*args,**kwargs):
   with lock:active[0]+=1;active[1]=max(active[1],active[0])
   time.sleep(.02)
   with lock:active[0]-=1
   return [file]
  with patch('catalog_media._delivery_parts',side_effect=split):
   with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(lambda _:delivery_parts(file,limit=100),range(3)))
  self.assertEqual(active[1],1)
  stop=threading.Event();stop.set()
  with self.assertRaisesRegex(RuntimeError,'INTERRUPTED'):delivery_parts(file,limit=100,stop=stop)
