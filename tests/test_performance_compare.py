import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import performance_compare as runner
from performance_series import verify_build


def build(root):
    for mod in ('CorpseProxyLab','CorpseProxyViewpoint'):
        (root/mod/'42').mkdir(parents=True)
        (root/mod/'common').mkdir()
        (root/mod/'42/mod.info').write_text('fixture')


def rows(session):
    return [dict(session=session,settings={'uncapped':True},protocol='v3',seed='same',count=32,
        topology='individual',test_mode='fps',profiling=False,driving={'movedBodies':32},cleanup={'returned':32},
        drive=dict(fps=100,low_1pct_fps=80,frame_ms_p95=12,frame_ms_p99=15,display={'width':1280})) for _ in range(2)]


class ComparisonTests(unittest.TestCase):
    def test_length_allows_one_percent_but_other_settings_stay_exact(self):
        a=rows('A');b=rows('B')
        for r in a:r['settings']['totalLength']=95.34112031612086
        for r in b:r['settings']['totalLength']=95.34106236394939
        runner.compare(a,b,2)
        self.assertTrue(runner.compatible_settings({'totalLength':99}, {'totalLength':100}))
        self.assertFalse(runner.compatible_settings({'totalLength':98.99}, {'totalLength':100}))
        self.assertTrue(runner.compatible_settings({'totalLength':0}, {'totalLength':0}))
        self.assertFalse(runner.compatible_settings({'totalLength':0}, {'totalLength':0.000001}))
        for bad in (97, float('nan'), float('inf'), '95.34112', True, -1):
            with self.subTest(bad=bad):
                b[0]['settings']['totalLength']=bad
                with self.assertRaises(ValueError): runner.compare(a,b,2)
        b=rows('B')
        with self.assertRaises(ValueError): runner.compare(a,b,2)
        self.assertFalse(runner.compatible_settings({'uncapped':True,'zoom':1}, {'uncapped':True,'zoom':1.000001}))

    def test_frozen_copy_and_installed_hashes(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'source';build(source)
            frozen=root/'frozen';manifest=runner.freeze(source,frozen)
            verify_build(source,frozen,manifest)
            (source/'CorpseProxyLab/42/mod.info').write_text('changed')
            self.assertEqual((frozen/'CorpseProxyLab/42/mod.info').read_text(),'fixture')
            with self.assertRaises(RuntimeError):verify_build(source,frozen,manifest)

    def test_two_clients_each_receives_repeat_count_and_frozen_build(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'source';build(source);out=root/'result';calls=[]
            def run(cmd,**kwargs):
                calls.append(cmd);target=Path(cmd[cmd.index('--output')+1]);target.mkdir()
                (target/'results.json').write_text(json.dumps(rows(target.name)))
            with patch.object(sys,'argv',['compare','--before',str(source),'--after',str(source),
                    '--repeats','2','--assets',str(root/'custom assets'),'--output',str(out)]),patch.object(runner,'stopped',return_value=True), \
                    patch.object(runner.subprocess,'run',side_effect=run):runner.main()
            self.assertEqual(len(calls),2)
            for cmd in calls:
                self.assertEqual(cmd[cmd.index('--repeats')+1],'2')
                self.assertEqual(cmd[cmd.index('--assets')+1],str((root/'custom assets').resolve()))
                self.assertEqual(cmd[cmd.index('--counts')+1:cmd.index('--preset')],['32'])
                self.assertNotIn('--profile',cmd);self.assertNotIn('--jfr',cmd)
            self.assertEqual(json.loads((out/'comparison.json').read_text())['fps']['change_percent'],0)

    def test_incompatible_or_incomplete_results_rejected(self):
        for key,value in [('settings',{}),('seed','other'),('session','A'),('cleanup',{'returned':31}),
                          ('driving',{'movedBodies':31}),('protocol','old')]:
            with self.subTest(key=key):
                a=rows('A');b=rows('B')
                for r in b:r[key]=value
                with self.assertRaises(ValueError):runner.compare(a,b,2)
        with self.assertRaises(ValueError):runner.compare(rows('A'),rows('B')[:1],2)

    def test_occupied_stand_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'out'
            with patch.object(sys,'argv',['compare','--before',t,'--output',str(out)]), \
                 patch.object(runner,'stopped',return_value=False):
                with self.assertRaises(RuntimeError):runner.main()
            self.assertFalse(out.exists())
