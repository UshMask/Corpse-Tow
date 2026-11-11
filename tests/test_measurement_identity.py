import sys,unittest,tempfile,json,hashlib
from pathlib import Path
sys.path.insert(0,'tools')
import performance_journal as j
class IdentityTests(unittest.TestCase):
 def test_identity(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t); self.assertIsNone(j.measurement_identity(p))
   manifest={'b.jar':'abc','a.lua':'def'}
   digest=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
   (p/'build.json').write_text(json.dumps(manifest))
   meta={'buildSha256':digest,'version':'0.8.0','startedAt':'2026-11-01T18:00:00+00:00'}
   (p/'measurement.json').write_text(json.dumps(meta))
   self.assertEqual(j.measurement_identity(p),meta)
   (p/'build.json').write_text(json.dumps(dict(reversed(list(manifest.items())))))
   self.assertEqual(j.measurement_identity(p),meta)
   (p/'build.json').write_text(json.dumps({'a.lua':'changed'}))
   with self.assertRaises(ValueError):j.measurement_identity(p)
if __name__=='__main__':unittest.main()
