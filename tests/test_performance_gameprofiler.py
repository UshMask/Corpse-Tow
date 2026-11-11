import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import performance_gameprofiler as gp


class StockProfilerTests(unittest.TestCase):
    def exercise(self,body_error=False,stop_error=False,expired=False):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'result';folder.mkdir()
            recording=root/'cache/Recording';recording.mkdir(parents=True)
            (recording/'fixture_GameProfiler_main_times.csv').write_text('12,1,2\n')
            commands=[]
            class Bridge:
                def request(self,name,arg):
                    commands.append(arg)
                    if arg=='stop' and stop_error: raise RuntimeError('connection lost')
                    return dict(active=arg=='stop',expired=expired,firstFrame=11,lastFrame=12)
            with patch.object(gp.time,'sleep'):
                try:
                    with gp.record(Bridge(),root,folder):
                        if body_error: raise ValueError('trip failed')
                except Exception as e: error=e
                else: error=None
            self.assertEqual(commands[-1],'restore')
            if body_error:self.assertIsInstance(error,ValueError)
            elif stop_error or expired:self.assertIsInstance(error,RuntimeError)
            else:
                self.assertIsNone(error)
                self.assertEqual(commands,['begin','stop','status','restore'])
                self.assertEqual((folder/'game-profiler/fixture_GameProfiler_main_times.csv').read_bytes(),
                                 (recording/'fixture_GameProfiler_main_times.csv').read_bytes())
                self.assertTrue((folder/'game-profiler.json').exists())

    def test_drain_and_copy(self):self.exercise()
    def test_trip_failure_restores(self):self.exercise(body_error=True)
    def test_connection_failure_restores_without_hiding_trip_error(self):self.exercise(True,True)
    def test_stop_failure_rejects(self):self.exercise(stop_error=True)
    def test_watchdog_rejects(self):self.exercise(expired=True)

if __name__=='__main__': unittest.main()
