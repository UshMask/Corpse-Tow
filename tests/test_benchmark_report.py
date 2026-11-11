import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('benchmark_report', Path('tools/benchmark_report.py'))
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class BenchmarkReportTests(unittest.TestCase):
    def test_slow_frames_use_reciprocal_mean_not_average_instantaneous_fps(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'CVPBenchmark-test.csv'
            path.write_text('frame_ms,tick_ms,heap_mb\n' + '10,1,128\n'*99 + '100,2,129\n')
            path.with_name('CVPBenchmark-test-meta.txt').write_text('variant=On\ncount=1\n')
            result = report.summarize(path)
            self.assertAlmostEqual(result['fps'], 100000/1090)
            self.assertEqual(result['low_1pct_fps'], 10)
            self.assertEqual(result['frames_over_50ms'], 1)
            self.assertEqual(result['heap_mb_max'], 129)

    def test_rejects_empty_or_invalid_intervals(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'CVPBenchmark-test.csv'
            path.with_name('CVPBenchmark-test-meta.txt').write_text('variant=Off\n')
            for values in ('', '0,0,0\n', 'nan,0,0\n'):
                path.write_text('frame_ms,tick_ms,heap_mb\n'+values)
                with self.assertRaises(ValueError):
                    report.summarize(path)

    def test_display_geometry_and_focus_are_required_for_verified_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'frames.csv'
            path.with_name('frames-meta.txt').write_text('variant=Tow\n')
            header='frame_ms,tick_ms,heap_mb,window_width,window_height,framebuffer_width,framebuffer_height,fullscreen,borderless,display_valid\n'
            row='10,0,0,1280,720,2560,1440,0,0,1\n'
            path.write_text(header+row*2)
            measured=report.summarize(path)
            self.assertTrue(measured['display_verified'])
            self.assertEqual(measured['display']['framebuffer_width'],2560)
            for bad in [row.replace('2560','1920'),row[:-2]+'0\n']:
                path.write_text(header+row+bad)
                with self.assertRaises(ValueError):report.summarize(path)
            path.write_text('frame_ms,tick_ms,heap_mb\n10,0,0\n')
            self.assertFalse(report.summarize(path)['display_verified'])
