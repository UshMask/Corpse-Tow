"""Focused link-update regression checks; full release checks remain in Project.ps1."""
from pathlib import Path
import os
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
MODULES = (
    'test_link_graph', 'test_link_service', 'test_link_runtime',
    'test_link_simulation', 'test_link_obstacles', 'test_link_extension',
    'test_link_rewire', 'test_link_clocks', 'test_equipment',
    'test_body_wear', 'test_link_performance', 'test_benchmark_series', 'test_idle_work', 'test_idle_runtime', 'test_link_kahlua', 'test_native_solver_adapter',
)

if __name__ == '__main__':
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / 'tests'))
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(not result.wasSuccessful())
