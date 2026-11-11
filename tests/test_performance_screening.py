"""Screening comparisons remain bounded and identify their limitations."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import performance_compare as runner


def make_build(path):
    for name in ('CorpseProxyLab', 'CorpseProxyViewpoint'):
        (path / name / '42').mkdir(parents=True)
        (path / name / 'common').mkdir()
        (path / name / '42' / 'mod.info').write_text('fixture')


def sample(session, fps):
    return dict(session=session, settings={'uncapped': True}, protocol='express', seed='seed', count=32,
        topology='individual', test_mode='fps', mode='Tow', profiling=False,
        driving={'movedBodies': 32}, cleanup={'returned': 32},
        drive={'fps': fps, 'low_1pct_fps': 80, 'frame_ms_p95': 12, 'frame_ms_p99': 15,
               'display': {'width': 1280}, 'focus': {'focused_fraction': 1.0}})


class ScreeningTests(unittest.TestCase):
    def run_comparison(self, order):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); build=root/'build'; make_build(build); out=root/'out'; calls=[]
            def run(command, **_):
                label=Path(command[command.index('--output')+1]).name
                calls.append(command); folder=out/label; folder.mkdir()
                (folder/'results.json').write_text(json.dumps([sample(label, 100 if label=='A' else 110)]))
            args=['compare','--before',str(build),'--after',str(build),'--preset','express',
                  '--order',order,'--output',str(out)]
            with patch.object(sys,'argv',args), patch.object(runner,'stopped',return_value=True), \
                 patch.object(runner.subprocess,'run',side_effect=run):
                runner.main()
            result=json.loads((out/'comparison.json').read_text())
            self.assertEqual([Path(c[c.index('--output')+1]).name for c in calls],list(order))
            self.assertTrue(all(c[c.index('--repeats')+1]=='1' and c[c.index('--preset')+1]=='express' for c in calls))
            self.assertEqual(result['order'],list(order))
            self.assertEqual(result['interpretation'],'screening-only')
            self.assertAlmostEqual(result['fps']['change_percent'],10)
            self.assertAlmostEqual(result['frame_ms_from_fps']['A'],10.0)
            self.assertAlmostEqual(result['frame_ms_from_fps']['B'],1000/110)
            self.assertEqual(result['focus']['A'][0]['focused_fraction'],1.0)
            self.assertTrue(any('uncertainty' in text for text in result['limitations']))

    def test_both_orders_preserve_before_after_identity(self):
        for order in ('AB','BA'):
            with self.subTest(order=order): self.run_comparison(order)

    def test_single_pair_checks_scene_and_instrumentation(self):
        left=[sample('A',100)]; right=[sample('B',110)]
        self.assertEqual(runner.compare(left,right,1)['interpretation'],'screening-only')
        right[0]['cleanup']['returned']=31
        with self.assertRaises(ValueError): runner.compare(left,right,1)
        right=[sample('B',0)]
        with self.assertRaises(ValueError): runner.compare(left,right,1)
        right=[sample('B',110)]; right[0]['profiling']=True
        with self.assertRaises(ValueError): runner.compare(left,right,1)

    def test_single_repeat_is_not_full_comparison(self):
        with patch.object(sys,'argv',['compare','--before','unused','--output','unused','--preset','full','--repeats','1']):
            with self.assertRaises(SystemExit): runner.main()

    def test_no_mod_cannot_compare_two_mod_builds(self):
        with patch.object(sys,'argv',['compare','--before','unused','--output','unused','--variant','Off']):
            with self.assertRaises(SystemExit): runner.main()
