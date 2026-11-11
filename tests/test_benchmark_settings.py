import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('settings',Path('tools/pz-test/settings.py'))
settings=importlib.util.module_from_spec(spec);spec.loader.exec_module(settings)


class SettingsTests(unittest.TestCase):
    def test_preserves_recorded_acceptance_and_applies_controlled_values(self):
        values=settings.parse(settings.merge('termsOfServiceVersion=2\nwidth=800\n','width=1280\n','termsOfServiceVersion=1\n'))
        self.assertEqual(values,{'termsOfServiceVersion':'2','width':'1280'})

    def test_recovers_only_existing_decision(self):
        self.assertIn('termsOfServiceVersion=1',settings.merge('termsOfServiceVersion=-1','', 'termsOfServiceVersion=1'))
        self.assertIn('termsOfServiceVersion=-1',settings.merge('termsOfServiceVersion=-1','',''))
        self.assertNotIn('termsOfServiceVersion',settings.merge('','width=1280',''))
