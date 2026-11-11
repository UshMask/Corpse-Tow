import csv
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('mp_auto',Path(__file__).resolve().parents[1]/'tools/mp-test/run.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ReportTests(unittest.TestCase):
    def measure(self,jump=0,gap=50):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'motion.csv'
            with p.open('w',newline='') as f:
                writer=csv.writer(f)
                writer.writerow('time,sequence,body,x,y,angle,sampleTime,sampleX,sampleY,carX,carY,kmh,forceN,loadAge,viewpoint,loadCount'.split(','))
                for i in range(10):
                    x=i*gap/50
                    body=x-5+(jump if i>=5 else 0)
                    writer.writerow([i*gap,i,'body1',body,0,0,i*gap,body,0,x,0,72,300,20,1,1])
            return module.metrics(p)
    def test_uniform_towing_has_no_jump(self):
        result=self.measure()
        self.assertEqual(result['jumpCandidates'],0)
        self.assertEqual(result['highSpeedLoadMeanN'],300)
        self.assertEqual(result['maxKmh'],72)
    def test_step_relative_to_vehicle_is_reported(self):
        self.assertGreater(self.measure(jump=1)['jumpCandidates'],0)
    def test_gap_is_not_reported_as_physics_jump(self):
        result=self.measure(jump=1,gap=250)
        self.assertEqual(result['jumpCandidates'],0)
        self.assertEqual(result['maxSampleGapMs'],250)
