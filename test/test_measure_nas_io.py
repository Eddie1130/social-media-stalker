"""Regression cases for the corrected sampler's accounting."""
import importlib.util
from pathlib import Path
import unittest
import subprocess
import sys
from unittest.mock import Mock

spec = importlib.util.spec_from_file_location('measure_io', Path(__file__).parents[1] / 'scripts/measure-nas-io.py')
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MeasureIoTests(unittest.TestCase):
    def test_elapsed_time_and_pid_reuse(self):
        def state(at, disk, processes):
            return {'at': at, 'disks': {'sata1': disk}, 'vm': {'pswpin': '2', 'pswpout': '3'},
                    'processes': processes, 'files': {}, 'unreadableProcesses': 0}
        before = state(10, [0]*11, {('1', '100'): {'name': 'node', 'write': 1024, 'read': 0}})
        after = state(12.5, [0,0,0,0,5,0,20,100,0,250,0], {
            ('1', '200'): {'name': 'reused', 'write': 999999, 'read': 0},
            ('2', '300'): {'name': 'new', 'write': 999999, 'read': 0}})
        result = module.difference(before, after)
        self.assertEqual(result['disks']['sata1']['writeKiBps'], 4)
        self.assertEqual(result['disks']['sata1']['writeAwaitMs'], 20)
        self.assertEqual(result['disks']['sata1']['utilPct'], 10)
        self.assertEqual(result['processCountersNotAdditive'], [])

    def test_existing_process_delta_and_log_rotation(self):
        before = {'at': 1, 'disks': {}, 'vm': {'pswpin': '0', 'pswpout': '0'},
                  'processes': {('5', '9'): {'name': 'chrome', 'write': 1024, 'read': 0}},
                  'files': {'id/log.db': (1, 100, 1)}, 'unreadableProcesses': 0}
        after = {**before, 'at': 3, 'processes': {('5', '9'): {'name': 'chrome', 'write': 5120, 'read': 0}},
                 'files': {'id/log.db': (2, 10, 2)}}
        result = module.difference(before, after)
        self.assertEqual(result['processCountersNotAdditive'][0]['writeKiBps'], 2)
        self.assertIsNone(result['changedLogFiles'][0]['growthBytes'])

    def test_removed_log_directory_is_skipped(self):
        directory = Mock()
        directory.iterdir.side_effect = FileNotFoundError('container removed')
        self.assertEqual(module.log_files(directory), ({}, 1))

    def test_nonfinite_interval_is_rejected_before_sampling(self):
        for value in ('nan', 'inf'):
            result = subprocess.run([sys.executable, str(spec.origin), '--interval', value],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('interval and samples', result.stderr)
