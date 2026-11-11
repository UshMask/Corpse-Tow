import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path('tools').resolve()))
from benchmark_gate import gate

class GateTests(unittest.TestCase):
    def test_exclusion_and_release_on_error(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'gate'
            with self.assertRaises(RuntimeError):
                with gate(path) as acquired:
                    self.assertTrue(acquired)
                    with gate(path) as second: self.assertFalse(second)
                    raise RuntimeError('failure')
            with gate(path) as acquired: self.assertTrue(acquired)

    def test_monitor_ignores_intermediate_results(self):
        spec=importlib.util.spec_from_file_location('monitor',Path('outputs/corpse-tow-lab/dashboard_monitor.py'))
        monitor=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitor)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);run=root/'local/runs/test';run.mkdir(parents=True)
            before=monitor.fingerprint(root)
            (run/'results.json').write_text('partial')
            (run/'plan.json').write_text('plan')
            self.assertEqual(before,monitor.fingerprint(root))
            (run/'journal-complete.json').write_text('complete')
            self.assertNotEqual(before,monitor.fingerprint(root))
