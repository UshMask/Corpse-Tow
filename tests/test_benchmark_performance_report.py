import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('performance_report',Path('tools/performance_report.py'))
report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)


class PerformanceReportTests(unittest.TestCase):
    def test_drive_only_keeps_full_driving_result(self):
        phase=dict(fps=100,low_1pct_fps=50,frame_ms_p99=20,frames_over_50ms=0)
        loop=dict(authority_ms_mean=2,heap_mb_max=1000)
        row=dict(count=32,mode='Tow',idle=None,idle_loop=None,drive=phase,drive_loop=loop)
        self.assertEqual(report.aggregate([row])[0]['phase'],'drive')
        with self.assertRaisesRegex(ValueError,'stationary control'):
            report.aggregate([row,dict(row,idle=phase,idle_loop=loop)])

    def test_smoke_test_is_not_reported_as_comparative_benchmark(self):
        with self.assertRaisesRegex(ValueError,'smoke tests'):
            report.aggregate([dict(quick=True)])

    def test_warm_series_is_not_mixed_with_cold_launches(self):
        with self.assertRaisesRegex(ValueError,'Warm-client'):
            report.aggregate([dict(series=True)])

    def test_preserves_variation_and_uses_presented_fps_with_separate_cpu_metrics(self):
        rows=[]
        for fps in (100,120,500):
            phase=dict(fps=fps,low_1pct_fps=fps/2,frame_ms_p99=2000/fps,
                       authority_ms_mean=0,heap_mb_max=0,frames_over_50ms=1)
            loop=dict(authority_ms_mean=2,heap_mb_max=1500)
            rows.append(dict(count=32,mode='Tow',idle=phase,drive=phase,idle_loop=loop,drive_loop=loop))
        result=report.aggregate(rows)
        self.assertEqual(len(result),2)
        for row in result:
            self.assertEqual(row['fps_median'],120)
            self.assertEqual((row['fps_min'],row['fps_max']),(100,500))
            self.assertEqual(row['authority_ms_median'],2)
            self.assertEqual(row['heap_mb_max'],1500)
            self.assertEqual(row['runs'],3)

    def test_does_not_merge_baseline_and_towing(self):
        phase=dict(fps=100,low_1pct_fps=50,frame_ms_p99=20,frames_over_50ms=0)
        loop=dict(authority_ms_mean=0,heap_mb_max=1000)
        rows=[dict(count=1,mode=mode,idle=phase,drive=phase,idle_loop=loop,drive_loop=loop) for mode in ('Off','On','Tow')]
        result=report.aggregate(rows)
        self.assertEqual(len(result),6)
        self.assertTrue(all(row['runs']==1 for row in result))
