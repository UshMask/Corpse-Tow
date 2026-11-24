from pathlib import Path
import sys
import tempfile
import unittest
from optional_files import load_optional_tool, optional_file
sys.path.insert(0,str(Path('tools').resolve()))

class GateTests(unittest.TestCase):
    def test_exclusion_and_release_on_error(self):
        optional_file('tools/benchmark_gate.py')
        from benchmark_gate import gate
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'gate'
            with self.assertRaises(RuntimeError):
                with gate(path) as acquired:
                    self.assertTrue(acquired)
                    with gate(path) as second: self.assertFalse(second)
                    raise RuntimeError('failure')
            with gate(path) as acquired: self.assertTrue(acquired)

    def test_monitor_ignores_intermediate_results(self):
        monitor=load_optional_tool('monitor','outputs/corpse-tow-lab/dashboard_monitor.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);run=root/'local/runs/test';run.mkdir(parents=True)
            before=monitor.fingerprint(root)
            (run/'results.json').write_text('partial')
            (run/'plan.json').write_text('plan')
            self.assertEqual(before,monitor.fingerprint(root))
            (run/'journal-complete.json').write_text('complete')
            self.assertNotEqual(before,monitor.fingerprint(root))
