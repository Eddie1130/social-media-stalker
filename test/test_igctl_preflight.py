"""The launcher must reject unsupported configuration before mutating Docker."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class PreflightTests(unittest.TestCase):
    def run_ctl(self, quota, *args):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            shutil.copy(Path(__file__).resolve().parents[1] / 'igctl', path / 'igctl')
            docker = path / 'docker'
            docker.write_text('''#!/bin/sh
if [ "$1" = info ]; then echo '["WARNING: No cpu cfs quota support"]'; exit 0; fi
case " $* " in *" --env-file custom.env "*) TEST_QUOTA=2.0 ;; esac
case " $* " in
  *" config "*) printf 'services:\\n  tiktok-catalog:\\n    cpus: "%s"\\n' "$TEST_QUOTA" ;;
  *) echo 'MUTATED' ;;
esac
''')
            docker.chmod(0o755)
            return subprocess.run(['sh', str(path / 'igctl'), *args], capture_output=True,
                                  text=True, timeout=5, env={**os.environ, 'PATH':folder + os.pathsep + os.environ['PATH'], 'TEST_QUOTA':quota})

    def test_unsupported_quota_rejected_before_up(self):
        result = self.run_ctl('2.0', 'preflight')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CPU CFS quotas unsupported', result.stderr)
        self.assertNotIn('MUTATED', result.stdout)

    def test_zero_quota_allows_deployment(self):
        result = self.run_ctl('0.0', 'preflight')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('MUTATED', result.stdout)

    def test_no_deps_catalog_rejected(self):
        result = self.run_ctl('0', 'up', '-d', '--no-deps', 'tiktok-catalog')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('MUTATED', result.stdout)

    def test_preflight_uses_the_requested_environment_file(self):
        result = self.run_ctl('0', 'preflight', '--env-file', 'custom.env')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CPU CFS quotas unsupported', result.stderr)
        self.assertNotIn('MUTATED', result.stdout)


class ShutdownBudgetTests(unittest.TestCase):
    def test_catalog_shutdown_budget_exceeds_noninterruptible_probe_and_browser_reap(self):
        import ast
        import re
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'tiktok/catalog_media.py').read_text())
        probe_timeout = max(keyword.value.value for node in ast.walk(tree)
                            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr == 'check_output'
                            for keyword in node.keywords if keyword.arg == 'timeout'
                            and isinstance(keyword.value, ast.Constant))
        service = (root / 'compose.tiktok.yml').read_text().split('  tiktok-catalog:', 1)[1].split('  tiktok-login:', 1)[0]
        value, unit = re.search(r'stop_grace_period:\s*(\d+)([sm])', service).groups()
        seconds = int(value) * (60 if unit == 'm' else 1)
        self.assertGreater(seconds, probe_timeout + 10,
                           'grace must cover the probe, browser group reaping and durable checkpoints')
