import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('journal',Path(__file__).resolve().parents[1]/'tools/performance_journal.py')
j=importlib.util.module_from_spec(spec);spec.loader.exec_module(j)


class JournalTests(unittest.TestCase):
    def test_new_modes_and_old_protocol_are_not_pooled(self):
        rows=[dict(count=32,mode='Tow',series=True,drive={'fps':60})]
        rows += [dict(count=32,mode='Tow',series=True,drive={'fps':60},
                      protocol='warm-client-series-v2',test_mode=mode)
                 for mode in ('fps','diagnostic','acceptance')]
        groups=j.normalize(rows)
        self.assertEqual(len(groups),4)
        self.assertEqual(sum(g['fps'] is not None for g in groups),2)

    def test_missing_metrics_and_protocols_stay_separate(self):
        rows=[dict(count=32,mode='Tow',drive={'fps':50},settings={}),
              dict(count=32,mode='Tow',drive={'fps':60},settings={},series=True)]
        groups=j.normalize(rows)
        self.assertEqual(len(groups),2)
        self.assertTrue(all(r['low'] is None and r['tick'] is None for r in groups))

    def test_profiles_do_not_supply_benchmark_fps(self):
        row=j.normalize([dict(count=32,mode='Tow',drive={'fps':50},profile=True)])[0]
        self.assertIsNone(row['fps']);self.assertTrue(row['diagnostic'])

    def test_only_matching_completion_marker_promotes_run(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'local/runs/new-run';folder.mkdir(parents=True)
            p=folder/'results.json';p.write_text(json.dumps([dict(count=32,mode='On',frames={'fps':100})]))
            j.build(root)
            load=lambda:json.loads((root/'local/performance/index.json').read_text(encoding='utf-8'))[0]['datasets'][0]['status']
            self.assertEqual(load(),'Архив / не проверен')
            (folder/'journal-complete.json').write_text(json.dumps({'results_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))
            j.build(root);self.assertEqual(load(),'Завершён')
            (folder/'failure.json').write_text('{}');j.build(root);self.assertEqual(load(),'Ошибка')


class DisplayGroupingTests(unittest.TestCase):
    def test_equal_core_size_different_framebuffers_are_not_pooled(self):
        rows=[dict(count=32,mode='Tow',settings={'width':1280,'height':720},
                   drive={'fps':60,'display':display}) for display in
              [None,{'window_width':1280,'window_height':720,'framebuffer_width':1280,'framebuffer_height':720},
               {'window_width':1280,'window_height':720,'framebuffer_width':2560,'framebuffer_height':1440}]]
        groups=j.normalize(rows)
        self.assertEqual(len(groups),3)
        self.assertEqual(sum(r['display_verified'] for r in groups),2)


if __name__=='__main__':unittest.main()
